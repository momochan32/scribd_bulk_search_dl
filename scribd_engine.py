"""
Scribd Document Downloader
==========================

A Selenium-based utility that loads a Scribd embed and saves it as a PDF.

Key behaviors:
1. Converts a Scribd document URL to the embed/content URL.
2. Opens the document in Chrome.
3. Scrolls through every page to trigger lazy loading.
4. Removes UI overlays without stripping layout classes needed for rendering.
5. Waits for fonts, images, and page geometry to settle.
6. Saves the PDF through Chrome DevTools Protocol with a larger timeout and
   stream-based PDF transfer for large documents.
"""

import argparse
import base64
import os
import random
import re
import sys
import tempfile
import time
from io import BytesIO
from urllib.parse import quote_plus, unquote, urlparse

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


DEFAULT_CDP_TIMEOUT_SECONDS = int(os.getenv("SCRIBD_CDP_TIMEOUT", "600"))
DEFAULT_RENDER_SETTLE_TIMEOUT_SECONDS = int(
    os.getenv("SCRIBD_RENDER_SETTLE_TIMEOUT", "30")
)
DEFAULT_SCROLL_DELAY_SECONDS = float(os.getenv("SCRIBD_SCROLL_DELAY", "0.15"))
DEFAULT_PAGE_LOAD_CONCURRENCY = max(
    1,
    int(os.getenv("SCRIBD_PAGE_LOAD_CONCURRENCY", "8")),
)
DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS = max(
    10,
    int(os.getenv("SCRIBD_PAGE_LOAD_TIMEOUT", "120")),
)
DEFAULT_EXPORT_BATCH_SIZE = max(
    1,
    int(os.getenv("SCRIBD_EXPORT_BATCH_SIZE", "8")),
)
PDF_STREAM_CHUNK_SIZE = int(os.getenv("SCRIBD_PDF_STREAM_CHUNK_SIZE", str(1024 * 1024)))
HEADLESS_ENABLED = os.getenv("SCRIBD_HEADLESS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
DEFAULT_PAPER_WIDTH_INCHES = 7.25
DEFAULT_PAPER_HEIGHT_INCHES = 10.5


def display_path(path):
    """Sanitize path representation to avoid leaking system usernames."""
    if not path:
        return ""
    home = os.path.expanduser("~")
    abs_path = os.path.abspath(os.path.expanduser(str(path)))
    if abs_path.startswith(home):
        return "~" + abs_path[len(home):]
    return abs_path


def open_in_file_manager(folder_path):
    """Cross-platform folder opener for Windows, macOS, and Linux."""
    if not folder_path or not os.path.exists(folder_path):
        return False
    abs_folder = os.path.abspath(folder_path)
    try:
        if sys.platform == "win32":
            os.startfile(abs_folder)
        elif sys.platform == "darwin":
            os.system(f'open "{abs_folder}"')
        else:
            os.system(f'xdg-open "{abs_folder}"')
        return True
    except Exception as exc:
        print(f"Failed to open folder: {exc}")
        return False


def build_chrome_options(runtime_profile_dir):
    """Create Chrome options for reliable headless PDF generation."""
    options = Options()

    if HEADLESS_ENABLED:
        options.add_argument("--headless=new")

    options.add_argument("--window-size=1600,2200")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument(f"--user-data-dir={runtime_profile_dir}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--force-color-profile=srgb")
    options.add_argument("--hide-scrollbars")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return options


def convert_scribd_link(url):
    """
    Convert a Scribd document URL to the embed/content URL.

    Args:
        url: Standard Scribd URL such as
            https://www.scribd.com/document/123456789/Document-Title
            or https://www.scribd.com/doc/123456789/Document-Title

    Returns:
        The embeddable content URL, or "Invalid Scribd URL" if no document id
        can be extracted.
    """
    match = re.search(r"https?://(?:www\.)?scribd\.com/(?:document|doc)/(\d+)", url)
    if not match:
        return "Invalid Scribd URL"

    return f"https://www.scribd.com/embeds/{match.group(1)}/content"


def get_filename_from_url(url):
    """
    Build an output filename from the last URL path segment and doc ID.

    Args:
        url: Scribd document URL.

    Returns:
        Filename ending in ".pdf".
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    last_segment = path.split("/")[-1] if path else "scribd_document"
    last_segment = unquote(last_segment)
    clean_segment = re.sub(r'[\\/*?:"<>|]', "", last_segment).strip()
    if not clean_segment:
        clean_segment = "scribd_document"

    match = re.search(r"/(?:document|doc)/(\d+)", url)
    doc_id = match.group(1) if match else None
    if doc_id and not clean_segment.endswith(doc_id):
        return f"{clean_segment}_{doc_id}.pdf"
    return f"{clean_segment}.pdf"


def configure_command_timeout(driver, timeout_seconds):
    """
    Increase the Selenium HTTP timeout used for ChromeDriver commands.

    Large image-heavy documents can spend minutes inside Page.printToPDF before
    ChromeDriver responds, so the default 120 second timeout is too small.
    """
    executor = getattr(driver, "command_executor", None)
    if executor is None:
        return

    client_config = getattr(executor, "client_config", None)
    if client_config is None:
        client_config = getattr(executor, "_client_config", None)

    if client_config is not None:
        client_config.timeout = timeout_seconds


def hide_cookie_dialogs(driver):
    """Dismiss and remove common cookie, consent, and privacy banners."""
    driver.execute_script(
        """
        const closeButtonSelectors = [
            '[class*="cookie"] [class*="close"]',
            '[class*="cookie"] [class*="dismiss"]',
            '[class*="cookie"] button[aria-label*="close"]',
            '[class*="cookie"] button[aria-label*="Close"]',
            '[class*="consent"] [class*="close"]',
            '[class*="consent"] [class*="dismiss"]',
            '[class*="banner"] [class*="close"]',
            '[class*="banner"] [class*="dismiss"]',
            '[class*="notice"] [class*="close"]',
            '[class*="notice"] [class*="dismiss"]',
            'button[class*="close"]',
            'button[aria-label="Close"]',
            'button[aria-label="close"]',
            'button[aria-label="Dismiss"]',
            '[data-dismiss]',
            '[role="button"][class*="close"]'
        ];

        closeButtonSelectors.forEach((selector) => {
            try {
                document.querySelectorAll(selector).forEach((button) => button.click());
            } catch (error) {}
        });

        const cookieSelectors = [
            '[class*="cookie"]',
            '[class*="Cookie"]',
            '[class*="consent"]',
            '[class*="Consent"]',
            '[class*="gdpr"]',
            '[class*="GDPR"]',
            '[id*="cookie"]',
            '[id*="Cookie"]',
            '[id*="consent"]',
            '[id*="gdpr"]',
            '[class*="privacy-notice"]',
            '[class*="Privacy"]',
            '[class*="cookie-banner"]',
            '[class*="cookie-notice"]',
            '[class*="cookie-popup"]',
            '[class*="cookie-modal"]',
            '[class*="CookieConsent"]',
            '[class*="notice-banner"]',
            '.cc-window',
            '.cc-banner',
            '#onetrust-consent-sdk',
            '#onetrust-banner-sdk',
            '.evidon-banner',
            '.truste_box_overlay',
            '[class*="osano-cm"]',
            '[id*="osano"]'
        ];

        cookieSelectors.forEach((selector) => {
            try {
                document.querySelectorAll(selector).forEach((element) => element.remove());
            } catch (error) {}
        });

        document.querySelectorAll('*').forEach((element) => {
            try {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                const text = (element.innerText || '').toLowerCase();
                const fixedAtTop =
                    (style.position === 'fixed' || style.position === 'sticky') &&
                    rect.top < 100;

                if (
                    fixedAtTop &&
                    (
                        text.includes('cookie') ||
                        text.includes('privacy') ||
                        text.includes('consent') ||
                        text.includes('analytics') ||
                        text.includes('advertising') ||
                        text.includes('personalization')
                    )
                ) {
                    element.remove();
                }
            } catch (error) {}
        });
        """
    )


def scroll_through_pages(driver, scroll_delay_seconds):
    """
    Scroll through all detected pages until the page count stabilizes.

    Scribd lazily renders more page nodes while scrolling, so a single snapshot
    of "[class*='page']" is not always enough for long documents.
    """
    scrolled_count = 0
    stable_rounds = 0
    last_total_pages = -1

    while stable_rounds < 2:
        page_elements = driver.find_elements("css selector", "[class*='page']")
        total_pages = len(page_elements)

        if total_pages == 0:
            print("No page elements were detected.")
            return 0

        if total_pages == last_total_pages:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_total_pages = total_pages

        if scrolled_count == 0:
            print(f"Found {total_pages} pages, scrolling...")
        elif total_pages > scrolled_count:
            print(f"Detected {total_pages} pages after lazy loading, continuing...")

        for index in range(scrolled_count, total_pages):
            driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});",
                page_elements[index],
            )
            time.sleep(scroll_delay_seconds)

            if (index + 1) % 10 == 0:
                print(f"  Scrolled {index + 1}/{total_pages} pages...")

        scrolled_count = total_pages
        time.sleep(0.5)

    print(f"All {scrolled_count} pages loaded.")
    return scrolled_count


def load_all_pages(driver):
    """Load Scribd pages directly, without simulating user scrolling."""
    page_count = driver.execute_script(
        """
        return window.docManager && window.docManager.pages
            ? Object.values(window.docManager.pages).filter(Boolean).length
            : 0;
        """
    )
    batch_count = max(
        1,
        (page_count + DEFAULT_PAGE_LOAD_CONCURRENCY - 1)
        // DEFAULT_PAGE_LOAD_CONCURRENCY,
    )
    document_timeout_seconds = (
        DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS * batch_count
    )
    configure_command_timeout(driver, document_timeout_seconds + 10)
    driver.set_script_timeout(document_timeout_seconds + 10)

    result = driver.execute_async_script(
        """
        const concurrency = arguments[0];
        const timeoutMs = arguments[1];
        const documentTimeoutMs = arguments[2];
        const done = arguments[arguments.length - 1];
        const manager = window.docManager;

        if (!manager || !manager.pages) {
            done({supported: false});
            return;
        }

        const pages = Object.values(manager.pages).filter(Boolean);
        const pending = pages.filter((page) => !page.innerPageElem);
        const active = new Map();
        const failed = [];
        const startedAt = Date.now();
        let nextIndex = 0;
        let completed = pages.length - pending.length;
        let finished = false;

        function finish() {
            if (finished) {
                return;
            }

            finished = true;
            clearInterval(timer);

            pages.forEach((page) => {
                if (!page.innerPageElem) {
                    return;
                }

                try {
                    page.display();
                } catch (error) {}

                try {
                    page.turnOnImages();
                } catch (error) {}
            });

            done({
                supported: true,
                total: pages.length,
                loaded: pages.filter((page) => page.innerPageElem).length,
                failed,
                elapsedMs: Date.now() - startedAt
            });
        }

        function launchMore() {
            while (active.size < concurrency && nextIndex < pending.length) {
                const page = pending[nextIndex++];

                try {
                    if (!page.loadHasStarted) {
                        page.load();
                    }

                    active.set(page.pageNum, {
                        page,
                        startedAt: Date.now()
                    });
                } catch (error) {
                    failed.push({
                        pageNum: page.pageNum,
                        reason: String(error)
                    });
                }
            }

            if (completed + failed.length >= pages.length) {
                finish();
            }
        }

        const timer = setInterval(() => {
            for (const [pageNum, state] of active) {
                if (state.page.innerPageElem) {
                    active.delete(pageNum);
                    completed += 1;
                    continue;
                }

                if (Date.now() - state.startedAt >= timeoutMs) {
                    active.delete(pageNum);
                    failed.push({
                        pageNum,
                        reason: 'page load timed out'
                    });
                }
            }

            if (Date.now() - startedAt >= documentTimeoutMs) {
                for (const [pageNum] of active) {
                    failed.push({
                        pageNum,
                        reason: 'document load timed out'
                    });
                }
                active.clear();
                finish();
                return;
            }

            launchMore();
        }, 50);

        launchMore();
        """,
        DEFAULT_PAGE_LOAD_CONCURRENCY,
        DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS * 1000,
        document_timeout_seconds * 1000,
    )

    if not result.get("supported"):
        print("Direct page loader unavailable; using scrolling fallback.")
        return scroll_through_pages(driver, DEFAULT_SCROLL_DELAY_SECONDS)

    total_pages = result["total"]
    loaded_pages = result["loaded"]
    elapsed_seconds = result["elapsedMs"] / 1000

    print(
        f"Loaded {loaded_pages}/{total_pages} pages directly "
        f"in {elapsed_seconds:.2f}s "
        f"(concurrency: {DEFAULT_PAGE_LOAD_CONCURRENCY})."
    )

    if result["failed"]:
        failed_pages = ", ".join(
            str(item["pageNum"])
            for item in result["failed"]
        )
        raise RuntimeError(
            "Failed to load Scribd page(s): "
            f"{failed_pages}"
        )

    return loaded_pages


def prepare_document_for_print(driver):
    """
    Remove UI chrome and make the scroll containers printable.

    The old version removed the .document_scroller class entirely, which can
    break descendant CSS needed by math- and font-heavy documents. We keep the
    class and only override the few layout properties that interfere with print.
    """
    result = driver.execute_script(
        """
        const removed = { toolbarTop: false, toolbarBottom: false, containers: 0 };

        const toolbarTop = document.querySelector('.toolbar_top');
        if (toolbarTop) {
            toolbarTop.remove();
            removed.toolbarTop = true;
        }

        const toolbarBottom = document.querySelector('.toolbar_bottom');
        if (toolbarBottom) {
            toolbarBottom.remove();
            removed.toolbarBottom = true;
        }

        document.querySelectorAll('.document_scroller').forEach((element) => {
            element.setAttribute('data-scribd-print-root', 'true');
            element.style.position = 'static';
            element.style.top = 'auto';
            element.style.bottom = 'auto';
            element.style.left = 'auto';
            element.style.right = 'auto';
            element.style.overflow = 'visible';
            element.style.maxHeight = 'none';
            element.style.height = 'auto';
            element.style.margin = '0';
            element.style.padding = '0';
            removed.containers += 1;
        });

        return removed;
        """
    )

    if result["toolbarTop"]:
        print("Top toolbar removed.")
    if result["toolbarBottom"]:
        print("Bottom toolbar removed.")

    print(f"Adjusted {result['containers']} scroll containers for print.")


def inject_print_styles(driver):
    """Install conservative print CSS without hiding Scribd document content."""
    driver.execute_script(
        """
        const existing = document.getElementById('scribd-print-styles');
        if (existing) {
            existing.remove();
        }

        const style = document.createElement('style');
        style.id = 'scribd-print-styles';
        style.textContent = `
            [class*="cookie"],
            [class*="Cookie"],
            [class*="consent"],
            [class*="Consent"],
            [class*="gdpr"],
            [class*="privacy-notice"],
            [class*="notice-banner"],
            [id*="cookie"],
            [id*="consent"],
            [class*="osano-cm"],
            [id*="osano"] {
                display: none !important;
                visibility: hidden !important;
                opacity: 0 !important;
                height: 0 !important;
                overflow: hidden !important;
            }

            [data-scribd-print-root="true"],
            .document_scroller {
                position: static !important;
                top: auto !important;
                right: auto !important;
                bottom: auto !important;
                left: auto !important;
                overflow: visible !important;
                height: auto !important;
                max-height: none !important;
                margin: 0 !important;
                padding: 0 !important;
            }

            @media print {
                html,
                body {
                    margin: 0 !important;
                    padding: 0 !important;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }

                .toolbar_top,
                .toolbar_bottom {
                    display: none !important;
                }

                [data-scribd-print-root="true"],
                .document_scroller {
                    position: static !important;
                    top: auto !important;
                    right: auto !important;
                    bottom: auto !important;
                    left: auto !important;
                    overflow: visible !important;
                    height: auto !important;
                    max-height: none !important;
                    margin: 0 !important;
                    padding: 0 !important;
                }

                mjx-container,
                .MathJax,
                .katex,
                math,
                svg {
                    visibility: visible !important;
                    overflow: visible !important;
                }
            }
        `;

        document.head.appendChild(style);
        """
    )

    print("Print CSS injected.")


def wait_for_render_stability(driver, timeout_seconds):
    """
    Wait for fonts, images, and page dimensions to settle before printing.

    This lowers the risk of exporting before math glyphs, SVG content, or web
    fonts finish rendering.
    """
    driver.set_script_timeout(timeout_seconds + 5)

    try:
        result = driver.execute_async_script(
            """
            const settleBudgetMs = arguments[0];
            const done = arguments[arguments.length - 1];
            const start = performance.now();
            let stableTicks = 0;
            let lastSample = '';

            function sample() {
                const pages = Array.from(document.querySelectorAll("[class*='page']"));
                const heights = pages.slice(0, 12).map((element) =>
                    Math.round(element.getBoundingClientRect().height)
                );
                const pendingImages = Array.from(document.images || []).filter(
                    (image) => !image.complete
                ).length;
                return JSON.stringify({
                    pageCount: pages.length,
                    heights,
                    pendingImages
                });
            }

            function finish(timedOut) {
                done({
                    timedOut,
                    sample: lastSample || sample()
                });
            }

            function tick() {
                lastSample = sample();
                const parsed = JSON.parse(lastSample);
                const isBusy = parsed.pendingImages > 0;

                if (!isBusy && lastSample === window.__scribdLastRenderSample) {
                    stableTicks += 1;
                } else {
                    stableTicks = 0;
                }

                window.__scribdLastRenderSample = lastSample;

                if (stableTicks >= 2) {
                    finish(false);
                    return;
                }

                if (performance.now() - start >= settleBudgetMs) {
                    finish(true);
                    return;
                }

                requestAnimationFrame(() => setTimeout(tick, 200));
            }

            const fontsReady = document.fonts && document.fonts.ready
                ? document.fonts.ready.catch(() => undefined)
                : Promise.resolve();

            fontsReady.finally(() => {
                requestAnimationFrame(() => setTimeout(tick, 200));
            });
            """,
            int(timeout_seconds * 1000),
        )
    except WebDriverException as error:
        print(f"Render settle check failed; continuing with best effort: {error}")
        return

    if result.get("timedOut"):
        print("Render settle reached its time budget; continuing with best effort.")
    else:
        print("Document render settled before export.")


def detect_document_paper_size(driver):
    """
    Infer a paper size from the first rendered Scribd page.

    Scribd pages often render as absolutely positioned HTML at a fixed CSS size.
    Using that page box as the print sheet size avoids splitting one Scribd page
    across multiple PDF pages.
    """
    paper_size = driver.execute_script(
        """
        const candidates = [
            '.outer_page',
            '.newpage',
            '.outer_page_container',
            "[class*='page']"
        ];

        for (const selector of candidates) {
            const element = document.querySelector(selector);
            if (!element) {
                continue;
            }

            const rect = element.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                return {
                    widthInches: rect.width / 96,
                    heightInches: rect.height / 96,
                    selector
                };
            }
        }

        return null;
        """
    )

    if not paper_size:
        return {
            "widthInches": DEFAULT_PAPER_WIDTH_INCHES,
            "heightInches": DEFAULT_PAPER_HEIGHT_INCHES,
            "selector": "default",
        }

    return {
        "widthInches": max(1.0, round(paper_size["widthInches"], 3)),
        "heightInches": max(1.0, round(paper_size["heightInches"], 3)),
        "selector": paper_size["selector"],
    }


def read_pdf_stream_to_file(driver, stream_handle, filename):
    """Read a streamed CDP PDF result and write it to disk in chunks."""
    try:
        with open(filename, "wb") as file_handle:
            while True:
                chunk = driver.execute_cdp_cmd(
                    "IO.read",
                    {
                        "handle": stream_handle,
                        "size": PDF_STREAM_CHUNK_SIZE,
                    },
                )

                data = chunk.get("data", "")
                if not data and chunk.get("eof"):
                    break

                if chunk.get("base64Encoded"):
                    file_handle.write(base64.b64decode(data))
                else:
                    file_handle.write(data.encode("utf-8"))

                if chunk.get("eof"):
                    break
    finally:
        driver.execute_cdp_cmd("IO.close", {"handle": stream_handle})


def load_page_batch(driver, page_numbers):
    """Load one bounded batch of page DOM and image assets."""
    configure_command_timeout(
        driver,
        DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS + 10,
    )
    driver.set_script_timeout(DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS + 10)

    result = driver.execute_async_script(
        """
        const pageNumbers = arguments[0];
        const timeoutMs = arguments[1];
        const done = arguments[arguments.length - 1];
        const manager = window.docManager;

        if (!manager || !manager.pages) {
            done({supported: false});
            return;
        }

        const states = pageNumbers.map((pageNum) => ({
            pageNum,
            page: manager.pages[pageNum],
            error: null
        }));
        const startedAt = Date.now();

        for (const state of states) {
            if (!state.page) {
                state.error = 'page object missing';
                continue;
            }

            try {
                if (!state.page.innerPageElem && !state.page.loadHasStarted) {
                    state.page.load();
                }
            } catch (error) {
                state.error = String(error);
            }
        }

        const timer = setInterval(() => {
            let ready = 0;

            for (const state of states) {
                if (state.error) {
                    ready += 1;
                    continue;
                }

                const page = state.page;
                if (!page.innerPageElem) {
                    continue;
                }

                try {
                    page.display();
                    if (!page._imagesTurnedOn) {
                        page.turnOnImages();
                    }
                } catch (error) {
                    state.error = String(error);
                    ready += 1;
                    continue;
                }

                const images = Array.from(
                    page.innerPageElem.querySelectorAll('img')
                );
                const pending = images.filter((image) => !image.complete);

                if (pending.length === 0) {
                    ready += 1;
                }
            }

            if (ready === states.length) {
                clearInterval(timer);
                done({
                    supported: true,
                    failed: states
                        .filter((state) => state.error)
                        .map((state) => ({
                            pageNum: state.pageNum,
                            reason: state.error
                        }))
                });
                return;
            }

            if (Date.now() - startedAt >= timeoutMs) {
                clearInterval(timer);
                done({
                    supported: true,
                    failed: states
                        .filter((state) => (
                            state.error ||
                            !state.page ||
                            !state.page.innerPageElem ||
                            Array.from(
                                state.page.innerPageElem.querySelectorAll('img')
                            ).some((image) => !image.complete)
                        ))
                        .map((state) => ({
                            pageNum: state.pageNum,
                            reason: state.error || 'page or image load timed out'
                        }))
                });
            }
        }, 50);
        """,
        list(page_numbers),
        DEFAULT_PAGE_LOAD_TIMEOUT_SECONDS * 1000,
    )

    if not result.get("supported"):
        raise RuntimeError("Scribd direct page loader is unavailable.")

    if result["failed"]:
        details = ", ".join(
            f"{item['pageNum']} ({item['reason']})"
            for item in result["failed"]
        )
        raise RuntimeError(f"Failed to load Scribd page(s): {details}")


def release_page_batch(driver, page_numbers):
    """Release printed page DOM and image resources from Chrome."""
    driver.execute_script(
        """
        const manager = window.docManager;
        if (!manager || !manager.pages) {
            return;
        }

        for (const pageNum of arguments[0]) {
            const page = manager.pages[pageNum];
            if (!page) {
                continue;
            }

            try {
                page.remove();
            } catch (error) {
                const container = document.getElementById(`outer_page_${pageNum}`);
                if (container) {
                    const inner = container.querySelector('.newpage');
                    if (inner) {
                        inner.remove();
                    }
                }
            }
        }
        """,
        list(page_numbers),
    )

    try:
        driver.execute_cdp_cmd("HeapProfiler.collectGarbage", {})
    except WebDriverException:
        pass


def save_pdf_pages_individually(
    driver,
    filename,
    timeout_seconds=DEFAULT_CDP_TIMEOUT_SECONDS,
    stop_event=None,
):
    from pypdf import PdfReader, PdfWriter

    configure_command_timeout(
        driver,
        timeout_seconds,
    )

    page_count = driver.execute_script(
        """
        return document.querySelectorAll(
            '.outer_page'
        ).length;
        """
    )

    if page_count <= 0:
        raise RuntimeError(
            "No .outer_page elements found."
        )

    print(
        f"Exporting {page_count} "
        "document pages in bounded batches "
        f"of {DEFAULT_EXPORT_BATCH_SIZE}..."
    )

    spool = tempfile.TemporaryDirectory(
        prefix="scribd-pdf-pages-"
    )
    page_files = []

    try:
        for index in range(page_count):
            if stop_event and stop_event.is_set():
                print(f"\n🛑 Pengunduhan dokumen dihentikan pada halaman {index + 1}/{page_count}.")
                raise KeyboardInterrupt("Stopped by user")

            if index % DEFAULT_EXPORT_BATCH_SIZE == 0:
                batch_end = min(
                    page_count,
                    index + DEFAULT_EXPORT_BATCH_SIZE,
                )
                batch_page_numbers = list(
                    range(index + 1, batch_end + 1)
                )
                print(
                    f"  Loading page batch "
                    f"{index + 1}-{batch_end}/{page_count}..."
                )
                load_page_batch(
                    driver,
                    batch_page_numbers,
                )

            page_info = driver.execute_script(
                """
                const targetIndex = arguments[0];

                const pages = Array.from(
                    document.querySelectorAll(
                        '.outer_page'
                    )
                );

                const target = pages[targetIndex];

                if (!target) {
                    return null;
                }

                /*
                 * Remove previous isolated-print style.
                 */
                const oldStyle = document.getElementById(
                    'isolated-page-print-style'
                );

                if (oldStyle) {
                    oldStyle.remove();
                }

                /*
                 * Restore all pages before measuring.
                 */
                pages.forEach((page) => {
                    page.style.removeProperty('display');
                    page.style.removeProperty('visibility');
                    page.style.removeProperty('position');
                    page.style.removeProperty('top');
                    page.style.removeProperty('left');
                    page.style.removeProperty('right');
                    page.style.removeProperty('bottom');
                    page.style.removeProperty('margin');
                    page.style.removeProperty('break-after');
                    page.style.removeProperty('page-break-after');
                    page.style.removeProperty('break-before');
                    page.style.removeProperty('page-break-before');
                });

                const rect = target.getBoundingClientRect();

                const width = Math.ceil(rect.width);
                const height = Math.ceil(rect.height);

                /*
                 * Mark the target instead of relying on nth-child.
                 */
                pages.forEach((page) => {
                    page.removeAttribute(
                        'data-export-target'
                    );
                });

                target.setAttribute(
                    'data-export-target',
                    'true'
                );

                const style = document.createElement(
                    'style'
                );

                style.id = 'isolated-page-print-style';

                style.textContent = `
                    @page {
                        size: ${width}px ${height}px;
                        margin: 0;
                    }

                    @media print {
                        html,
                        body {
                            width: ${width}px !important;
                            height: ${height}px !important;
                            min-width: ${width}px !important;
                            min-height: ${height}px !important;
                            max-width: ${width}px !important;
                            max-height: ${height}px !important;

                            margin: 0 !important;
                            padding: 0 !important;

                            overflow: hidden !important;

                            -webkit-print-color-adjust:
                                exact !important;

                            print-color-adjust:
                                exact !important;
                        }

                        .outer_page {
                            display: none !important;
                        }

                        .outer_page[
                            data-export-target="true"
                        ] {
                            display: block !important;
                            visibility: visible !important;

                            position: absolute !important;

                            top: 0 !important;
                            left: 0 !important;
                            right: auto !important;
                            bottom: auto !important;

                            width: ${width}px !important;
                            height: ${height}px !important;

                            min-width: 0 !important;
                            min-height: 0 !important;

                            max-width: none !important;
                            max-height: none !important;

                            margin: 0 !important;
                            padding: 0 !important;

                            transform: none !important;

                            break-before: auto !important;
                            break-after: auto !important;
                            break-inside: auto !important;

                            page-break-before:
                                auto !important;

                            page-break-after:
                                auto !important;

                            page-break-inside:
                                auto !important;

                            overflow: hidden !important;
                        }
                    }
                `;

                document.head.appendChild(style);

                return {
                    width,
                    height
                };
                """,
                index,
            )

            if not page_info:
                print(
                    f"  Skipping page "
                    f"{index + 1}: element missing"
                )
                continue

            width_px = int(page_info["width"])
            height_px = int(page_info["height"])

            if width_px <= 0 or height_px <= 0:
                print(
                    f"  Skipping page {index + 1}: "
                    f"invalid geometry "
                    f"{width_px}x{height_px}"
                )
                continue

            width_inches = width_px / 96.0
            height_inches = height_px / 96.0

            print(
                f"  Page {index + 1}/{page_count} "
                f"{width_px}x{height_px}px "
                f"-> "
                f'{width_inches:.3f}"'
                f'x{height_inches:.3f}"'
            )

            driver.execute_cdp_cmd(
                "Emulation.setEmulatedMedia",
                {
                    "media": "print",
                },
            )

            result = driver.execute_cdp_cmd(
                "Page.printToPDF",
                {
                    "landscape": False,
                    "displayHeaderFooter": False,
                    "printBackground": True,

                    "scale": 1,

                    "paperWidth": width_inches,
                    "paperHeight": height_inches,

                    "marginTop": 0,
                    "marginBottom": 0,
                    "marginLeft": 0,
                    "marginRight": 0,

           
                    "preferCSSPageSize": True,

                
                    "pageRanges": "1",

                    "transferMode": "ReturnAsBase64",
                },
            )

            pdf_bytes = base64.b64decode(
                result["data"]
            )

            page_reader = PdfReader(BytesIO(pdf_bytes))
            if len(page_reader.pages) != 1:
                raise RuntimeError(
                    f"Document page "
                    f"{index + 1} produced "
                    f"{len(page_reader.pages)} "
                    "PDF sheets; expected exactly 1."
                )

            page_path = os.path.join(
                spool.name,
                f"page-{index + 1:08d}.pdf",
            )
            with open(page_path, "wb") as page_handle:
                page_handle.write(pdf_bytes)
            page_files.append(page_path)

            print(
                f"    OK: exactly 1 PDF sheet"
            )

            is_batch_end = (
                (index + 1) % DEFAULT_EXPORT_BATCH_SIZE == 0
                or index + 1 == page_count
            )
            if is_batch_end:
                release_page_batch(
                    driver,
                    batch_page_numbers,
                )

        if not page_files:
            raise RuntimeError(
                "No valid document pages "
                "were exported."
            )

        print(
            f"Merging {len(page_files)} "
            "disk-spooled PDF pages..."
        )
        writer = PdfWriter()
        try:
            for page_path in page_files:
                writer.append(page_path)
            with open(filename, "wb") as output_handle:
                writer.write(output_handle)
        finally:
            writer.close()

    finally:
        spool.cleanup()

    return os.path.abspath(filename)

def download_scribd_document(
    url,
    output_dir=None,
    driver=None,
    close_driver=False,
    stop_event=None,
):
    """
    Download a single Scribd document as a PDF.

    Args:
        url: Scribd document URL.
        output_dir: Optional directory to store the output PDF.
        driver: Optional existing Selenium WebDriver instance.
        close_driver: Whether to close the driver after export.
        stop_event: Optional threading.Event for cancellation.

    Returns:
        Tuple of (saved_path, was_skipped).
    """
    converted_url = convert_scribd_link(url)
    if converted_url == "Invalid Scribd URL":
        raise ValueError(
            f"Invalid Scribd document URL: {url}\n"
            "Example: https://www.scribd.com/document/123456789/Title"
        )

    pdf_filename = get_filename_from_url(url)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        target_path = os.path.join(output_dir, pdf_filename)
    else:
        target_path = pdf_filename

    if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
        print(f"  [Skip] Document already downloaded: {display_path(target_path)}")
        return os.path.abspath(target_path), True

    if stop_event and stop_event.is_set():
        raise KeyboardInterrupt("Stopped by user")

    print(f"\nProcessing: {url}")
    print(f"Link embed: {converted_url}")
    print(f"Target PDF: {display_path(target_path)}")

    created_profile_dir = None
    created_driver = False

    try:
        if driver is None:
            created_profile_dir = tempfile.TemporaryDirectory(
                prefix="scribd-chrome-profile-"
            )
            print("Starting Chrome browser...")
            options = build_chrome_options(created_profile_dir.name)
            driver = webdriver.Chrome(options=options)
            created_driver = True

        driver.get(converted_url)
        time.sleep(1)

        if stop_event and stop_event.is_set():
            raise KeyboardInterrupt("Stopped by user")

        hide_cookie_dialogs(driver)
        print("Cookie dialogs hidden.")

        total_pages = driver.execute_script(
            """
            return document.querySelectorAll('.outer_page').length;
            """
        )

        if total_pages == 0:
            raise RuntimeError(
                "No printable document pages were detected."
            )

        prepare_document_for_print(driver)
        inject_print_styles(driver)

        print(f"\nSaving PDF as: {display_path(target_path)}")
        print("  Export mode: Individual document pages")
        print("  Margins: None")
        print("  Headers/Footers: Disabled")
        print(
            "  ChromeDriver command timeout: "
            f"{DEFAULT_CDP_TIMEOUT_SECONDS}s"
        )

        driver.execute_script("window.scrollTo(0, 0)")

        saved_path = save_pdf_pages_individually(
            driver,
            target_path,
            stop_event=stop_event,
        )

        if not saved_path:
            raise RuntimeError("PDF export failed.")

        print(f"PDF saved successfully to: {display_path(saved_path)}")
        return saved_path, False

    finally:
        if (created_driver or close_driver) and driver is not None:
            try:
                driver.quit()
                print("Browser closed.")
            except Exception:
                pass
        if created_profile_dir is not None:
            try:
                created_profile_dir.cleanup()
            except Exception:
                pass


def get_downloaded_document_ids(output_dir):
    """Scan output directory for document IDs of already downloaded PDFs."""
    if not output_dir or not os.path.exists(output_dir):
        return set()
    existing_ids = set()
    try:
        for fname in os.listdir(output_dir):
            if fname.endswith(".pdf"):
                match = re.search(r"_(\d+)\.pdf$", fname)
                if match:
                    existing_ids.add(match.group(1))
                else:
                    match2 = re.search(r"^(\d+)\.pdf$", fname)
                    if match2:
                        existing_ids.add(match2.group(1))
    except Exception:
        pass
    return existing_ids


def search_scribd_documents(
    keyword,
    limit=10,
    existing_ids=None,
    driver=None,
    close_driver=False,
    stop_event=None,
):
    """
    Search Scribd for documents matching a keyword and return a list of document dicts.

    Args:
        keyword: Search query string.
        limit: Maximum number of document URLs to return.
        existing_ids: Optional set of document IDs to skip (already downloaded).
        driver: Optional existing Selenium WebDriver.
        close_driver: Whether to close driver on completion.
        stop_event: Optional threading.Event for cancellation.

    Returns:
        List of dicts with keys: 'url', 'title', 'id'.
    """
    keyword = keyword.strip()
    if not keyword:
        return []

    if existing_ids is None:
        existing_ids = set()

    print(f"\nSearching Scribd for: '{keyword}' (limit: {limit} documents)...")
    quoted_query = quote_plus(keyword)

    created_profile_dir = None
    created_driver = False

    try:
        if driver is None:
            created_profile_dir = tempfile.TemporaryDirectory(
                prefix="scribd-search-profile-"
            )
            options = build_chrome_options(created_profile_dir.name)
            driver = webdriver.Chrome(options=options)
            created_driver = True

        documents_by_id = {}
        page = 1
        max_search_pages = max(10, (limit + 39) // 40 + 5)

        while len(documents_by_id) < limit and page <= max_search_pages:
            if stop_event and stop_event.is_set():
                print(f"\n🛑 Pencarian kata kunci '{keyword}' dihentikan oleh pengguna.")
                break

            search_url = (
                f"https://www.scribd.com/search?query={quoted_query}&page={page}"
            )
            print(f"Fetching search results page {page}...")
            driver.get(search_url)

            # Wait for React SPA hydration (interruptible)
            if stop_event:
                if stop_event.wait(3.0):
                    print(f"\n🛑 Pencarian dihentikan oleh pengguna.")
                    break
            else:
                time.sleep(3)

            if stop_event and stop_event.is_set():
                print(f"\n🛑 Pencarian kata kunci '{keyword}' dihentikan oleh pengguna.")
                break

            hide_cookie_dialogs(driver)

            links = driver.find_elements(By.TAG_NAME, "a")
            initial_count = len(documents_by_id)
            skipped_existing = 0

            for link in links:
                if stop_event and stop_event.is_set():
                    break

                try:
                    href = link.get_attribute("href")
                    if not href:
                        continue

                    match = re.search(
                        r"https://www\.scribd\.com/(?:document|doc)/(\d+)(?:/([^/?#]+))?",
                        href,
                    )
                    if not match:
                        continue

                    doc_id = match.group(1)
                    slug = match.group(2) or ""

                    if doc_id in existing_ids:
                        skipped_existing += 1
                        continue

                    if doc_id not in documents_by_id:
                        title = link.text.strip()
                        if not title:
                            title = link.get_attribute("title") or slug.replace("-", " ")

                        clean_url = (
                            f"https://www.scribd.com/document/{doc_id}/{slug}"
                            if slug
                            else f"https://www.scribd.com/document/{doc_id}"
                        )
                        documents_by_id[doc_id] = {
                            "id": doc_id,
                            "title": title or f"Document {doc_id}",
                            "url": clean_url,
                        }

                        if len(documents_by_id) >= limit:
                            break
                except Exception:
                    continue

            new_found = len(documents_by_id) - initial_count
            print(
                f"  Page {page}: found {new_found} new documents "
                f"(total collected: {len(documents_by_id)})"
            )

            if new_found == 0:
                break

            page += 1

        results = list(documents_by_id.values())[:limit]
        print(f"Total documents found matching '{keyword}': {len(results)}\n")
        return results

    finally:
        if (created_driver or close_driver) and driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        if created_profile_dir is not None:
            try:
                created_profile_dir.cleanup()
            except Exception:
                pass


def save_search_results_file(keyword, documents, output_dir="output"):
    """Save extracted search URLs to a readable text file."""
    os.makedirs(output_dir, exist_ok=True)
    slug = re.sub(r"[^\w\-]", "_", keyword.lower()).strip("_")
    filename = os.path.join(output_dir, f"search_results_{slug}.txt")

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# Scribd Search Results for: {keyword}\n")
        f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Total: {len(documents)}\n\n")
        for doc in documents:
            f.write(f"{doc['url']}  # {doc['title']}\n")

    print(f"Saved {len(documents)} document URLs to: {filename}")
    return filename


def load_urls_from_file(filepath):
    """Read document URLs from a text file, ignoring empty lines and comments."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.search(r"https?://\S+", line)
            if match:
                urls.append(match.group(0))
            else:
                urls.append(line)
    return urls


def bulk_download_documents(
    items_or_urls,
    output_dir="output",
    min_delay=1.0,
    max_delay=3.0,
    delay_between=None,
    stop_event=None,
):
    """
    Download multiple documents in sequence, reusing the Chrome instance when possible.

    Args:
        items_or_urls: List of URL strings or list of dicts with 'url' key.
        output_dir: Folder to save PDFs.
        min_delay: Minimum random delay in seconds between downloads.
        max_delay: Maximum random delay in seconds between downloads.
        delay_between: Optional legacy fixed delay in seconds (overrides min/max if provided).
        stop_event: Optional threading.Event for cancellation.

    Returns:
        Summary dict of download stats.
    """
    if delay_between is not None:
        min_delay = float(delay_between)
        max_delay = float(delay_between)

    # Guarantee min_delay <= max_delay
    if min_delay > max_delay:
        min_delay, max_delay = max_delay, min_delay

    urls = []
    for item in items_or_urls:
        if isinstance(item, dict) and "url" in item:
            urls.append(item["url"])
        elif isinstance(item, str) and item.strip():
            urls.append(item.strip())

    total = len(urls)
    if total == 0:
        print("No URLs provided for bulk download.")
        return {"total": 0, "success": 0, "skipped": 0, "failed": 0}

    os.makedirs(output_dir, exist_ok=True)
    print("\n========================================================")
    print(f" Starting Bulk Download: {total} documents")
    print(f" Destination Directory: {display_path(output_dir)}")
    if min_delay == max_delay:
        print(f" Delay between files: {max_delay:.1f}s")
    else:
        print(f" Random delay range: {min_delay:.1f}s - {max_delay:.1f}s ({int(min_delay*1000)} - {int(max_delay*1000)} ms)")
    print("========================================================\n")

    stats = {
        "total": total,
        "success": 0,
        "skipped": 0,
        "failed": 0,
        "failed_urls": [],
    }

    driver = None
    profile_dir = None

    def start_driver():
        nonlocal driver, profile_dir
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        if profile_dir is not None:
            try:
                profile_dir.cleanup()
            except Exception:
                pass
        profile_dir = tempfile.TemporaryDirectory(prefix="scribd-bulk-profile-")
        options = build_chrome_options(profile_dir.name)
        driver = webdriver.Chrome(options=options)

    try:
        start_driver()

        for idx, url in enumerate(urls, 1):
            if stop_event and stop_event.is_set():
                print("\n🛑 Proses bulk download dihentikan oleh pengguna.")
                break

            print(f"\n--- [{idx}/{total}] ---")
            try:
                saved_path, was_skipped = download_scribd_document(
                    url,
                    output_dir=output_dir,
                    driver=driver,
                    close_driver=False,
                    stop_event=stop_event,
                )
                if was_skipped:
                    stats["skipped"] += 1
                else:
                    stats["success"] += 1
                    if idx < total and max_delay > 0:
                        actual_delay = random.uniform(min_delay, max_delay)
                        delay_ms = int(actual_delay * 1000)
                        print(f"⏱️ Jeda acak {actual_delay:.2f}s ({delay_ms} ms) sebelum dokumen berikutnya...")
                        if stop_event:
                            if stop_event.wait(actual_delay):
                                print("\n🛑 Proses dihentikan saat jeda waktu.")
                                break
                        else:
                            time.sleep(actual_delay)

            except KeyboardInterrupt:
                print("\n🛑 Proses download dihentikan.")
                break
            except Exception as exc:
                print(f"  [ERROR] Failed to download {url}: {exc}")
                stats["failed"] += 1
                stats["failed_urls"].append((url, str(exc)))
                try:
                    driver.current_url
                except Exception:
                    print("  Restarting browser after unexpected failure...")
                    start_driver()

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
            print("Bulk downloader browser closed.")
        if profile_dir is not None:
            try:
                profile_dir.cleanup()
            except Exception:
                pass

    print("\n========================================================")
    print(" Bulk Download Summary")
    print("========================================================")
    print(f" Total Requested:         {stats['total']}")
    print(f" Successfully Downloaded: {stats['success']}")
    print(f" Skipped (Pre-existing):  {stats['skipped']}")
    print(f" Failed Downloads:        {stats['failed']}")
    if stats["failed_urls"]:
        print("\nFailed Documents:")
        for failed_url, reason in stats["failed_urls"]:
            print(f" - {failed_url} (Reason: {reason})")
    print("========================================================\n")

    return stats


def search_and_bulk_download_keywords(
    keywords,
    limit_per_keyword=5,
    output_dir="output",
    min_delay=1.0,
    max_delay=5.0,
    stop_event=None,
):
    """
    Search Scribd and download documents for multiple keywords sequentially.

    Args:
        keywords: String (separated by comma or newline) or list of strings.
        limit_per_keyword: Max new documents to download per keyword.
        output_dir: Folder to save PDFs.
        min_delay: Minimum random pause between downloads (seconds).
        max_delay: Maximum random pause between downloads (seconds).
        stop_event: Optional threading.Event for cancellation.

    Returns:
        Summary statistics dictionary.
    """
    if isinstance(keywords, str):
        raw_list = keywords.replace("\n", ",").split(",")
        keywords = [k.strip() for k in raw_list if k.strip()]
    elif isinstance(keywords, (list, tuple, set)):
        keywords = [str(k).strip() for k in keywords if str(k).strip()]
    else:
        keywords = []

    total_keywords = len(keywords)
    if total_keywords == 0:
        print("⚠️ Tidak ada kata kunci yang valid untuk dicari.")
        return {
            "total_keywords": 0,
            "processed_keywords": 0,
            "total_downloaded": 0,
            "total_skipped": 0,
            "total_failed": 0,
            "stopped": False,
        }

    os.makedirs(output_dir, exist_ok=True)
    print("\n" + "=" * 60)
    print(f" 🚀 Memulai Pemrosesan {total_keywords} Kata Kunci")
    print(f" Target Dokumen Baru: {limit_per_keyword} per kata kunci")
    print(f" Rentang Jeda Acak:   {min_delay:.1f}s - {max_delay:.1f}s ({int(min_delay*1000)} - {int(max_delay*1000)} ms)")
    print(f" Folder Penyimpanan:  {display_path(output_dir)}")
    print("=" * 60 + "\n")

    overall_stats = {
        "total_keywords": total_keywords,
        "processed_keywords": 0,
        "total_downloaded": 0,
        "total_skipped": 0,
        "total_failed": 0,
        "stopped": False,
    }

    for k_idx, keyword in enumerate(keywords, 1):
        if stop_event and stop_event.is_set():
            print("\n🛑 Seluruh antrean kata kunci dihentikan oleh pengguna.")
            overall_stats["stopped"] = True
            break

        print("\n" + "=" * 60)
        print(f" 🔍 Kata Kunci [{k_idx}/{total_keywords}]: '{keyword}'")
        print("=" * 60)

        existing_ids = get_downloaded_document_ids(output_dir)
        if existing_ids:
            print(f"ℹ️ Ditemukan {len(existing_ids)} file PDF yang sudah ada sebelumnya di folder.")

        docs = search_scribd_documents(
            keyword,
            limit=limit_per_keyword,
            existing_ids=existing_ids,
            stop_event=stop_event,
            close_driver=True,
        )

        if stop_event and stop_event.is_set():
            overall_stats["stopped"] = True
            break

        if not docs:
            print(f"⚠️ Tidak ada dokumen baru ditemukan untuk kata kunci '{keyword}'. Lanjut ke kata kunci berikutnya...\n")
            overall_stats["processed_keywords"] += 1
            continue

        save_search_results_file(keyword, docs, output_dir=output_dir)

        print(f"\n🚀 Memulai download {len(docs)} dokumen untuk '{keyword}'...")
        stats = bulk_download_documents(
            docs,
            output_dir=output_dir,
            min_delay=min_delay,
            max_delay=max_delay,
            stop_event=stop_event,
        )

        overall_stats["total_downloaded"] += stats.get("success", 0)
        overall_stats["total_skipped"] += stats.get("skipped", 0)
        overall_stats["total_failed"] += stats.get("failed", 0)
        overall_stats["processed_keywords"] += 1

        if stop_event and stop_event.is_set():
            overall_stats["stopped"] = True
            break

    print("\n" + "=" * 60)
    print(" 🎉 Ringkasan Seluruh Pemrosesan Multi-Kata Kunci")
    print("=" * 60)
    print(f" Total Kata Kunci:       {overall_stats['total_keywords']}")
    print(f" Kata Kunci Selesai:     {overall_stats['processed_keywords']}")
    print(f" Total PDF Diunduh:      {overall_stats['total_downloaded']}")
    print(f" Total PDF Dilewati:     {overall_stats['total_skipped']}")
    print(f" Total Gagal:            {overall_stats['total_failed']}")
    if overall_stats["stopped"]:
        print(" Status:                 🛑 Dihentikan sebelum selesai")
    else:
        print(" Status:                 ✅ Selesai")
    print("=" * 60 + "\n")

    return overall_stats


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Scribd Downloader - Download documents as PDF individually, via search, or in bulk."
    )
    parser.add_argument(
        "-u", "--url",
        help="Scribd document URL to download.",
        type=str,
    )
    parser.add_argument(
        "-s", "--search",
        help="Keyword to search Scribd for and bulk download found documents.",
        type=str,
    )
    parser.add_argument(
        "-l", "--limit",
        help="Maximum number of documents to fetch from search (default: 10).",
        type=int,
        default=10,
    )
    parser.add_argument(
        "-f", "--file",
        help="Path to a text file containing Scribd URLs to bulk download (one per line).",
        type=str,
    )
    parser.add_argument(
        "-o", "--output",
        help="Output directory for downloaded PDFs (default: 'output' for bulk/search, current directory for single URL).",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--delay",
        help="Seconds to wait between downloads in bulk mode (default: 3).",
        type=float,
        default=3.0,
    )
    parser.add_argument(
        "--no-download",
        help="When used with --search, only search and save URL list without downloading PDFs.",
        action="store_true",
    )
    return parser.parse_args()


def interactive_menu():
    """Interactive prompt for choosing download mode."""
    print("\n========================================================")
    print("               SCRIBD DOCUMENT DOWNLOADER               ")
    print("========================================================")
    print(" [1] Cari Kata Kunci & Download Otomatis  (Paling Praktis)")
    print(" [2] Download dari 1 Link Dokumen Scribd")
    print(" [3] Download Banyak dari File Teks (urls.txt)")
    print(" [0] Keluar")
    print("--------------------------------------------------------")
    choice = input("Pilih nomor [1-3] (Langsung tekan Enter untuk No 1): ").strip()
    return choice if choice else "1"


def main():
    """Run the downloader via CLI arguments or interactive menu."""
    args = parse_arguments()

    # CLI Flag: Single URL
    if args.url:
        try:
            download_scribd_document(
                args.url,
                output_dir=args.output,
                close_driver=True,
            )
        except (RuntimeError, WebDriverException, ValueError) as error:
            print(f"Export failed: {error}")
            sys.exit(1)
        return

    # CLI Flag: Bulk from file
    if args.file:
        try:
            urls = load_urls_from_file(args.file)
        except Exception as error:
            print(f"Error reading file: {error}")
            sys.exit(1)

        out_dir = args.output or "output"
        bulk_download_documents(
            urls,
            output_dir=out_dir,
            delay_between=args.delay,
        )
        if sys.platform == "darwin" and os.path.exists(out_dir):
            os.system(f'open "{os.path.abspath(out_dir)}"')
        return

    # CLI Flag: Search keyword
    if args.search:
        out_dir = args.output or "output"
        docs = search_scribd_documents(
            args.search,
            limit=args.limit,
            close_driver=True,
        )
        if docs:
            save_search_results_file(args.search, docs, output_dir=out_dir)
            if not args.no_download:
                bulk_download_documents(
                    docs,
                    output_dir=out_dir,
                    delay_between=args.delay,
                )
                if sys.platform == "darwin" and os.path.exists(out_dir):
                    os.system(f'open "{os.path.abspath(out_dir)}"')
        return

    # No CLI flags -> Interactive mode
    choice = interactive_menu()

    # Opsi 1: Cari Kata Kunci & Download Otomatis
    if choice == "1":
        keyword = input("\n🔍 Masukkan kata kunci pencarian (misal: Python Dasar): ").strip()
        if not keyword:
            print("❌ Kata kunci tidak boleh kosong.")
            return

        limit_input = input("📄 Mau download berapa dokumen? [tekan Enter untuk 5]: ").strip()
        limit = (
            int(limit_input)
            if limit_input.isdigit() and int(limit_input) > 0
            else 5
        )

        default_out = os.path.expanduser("~/Downloads/Scribd")
        folder_prompt = input(
            "📁 Simpan file ke folder mana? [tekan Enter untuk '~/Downloads/Scribd']: "
        ).strip()
        out_dir = os.path.expanduser(folder_prompt) if folder_prompt else default_out

        existing_ids = get_downloaded_document_ids(out_dir)
        if existing_ids:
            print(f"ℹ️ Ditemukan {len(existing_ids)} file PDF yang sudah pernah diunduh di folder tujuan.")
            print("   Sistem akan otomatis melewati file-file lama dan mencari dokumen baru.")

        print(f"\nSedang mencari {limit} dokumen baru untuk kata kunci '{keyword}'...")
        docs = search_scribd_documents(
            keyword,
            limit=limit,
            existing_ids=existing_ids,
            close_driver=True,
        )
        if not docs:
            print(f"❌ Tidak ditemukan dokumen baru untuk kata kunci '{keyword}'.")
            return

        save_search_results_file(keyword, docs, output_dir=out_dir)

        print(f"\n🚀 Memulai download {len(docs)} file PDF ke folder '{display_path(out_dir)}'...")
        bulk_download_documents(
            docs,
            output_dir=out_dir,
            delay_between=args.delay if args.delay else 2.5,
        )

        # Otomatis buka folder di Mac Finder agar pengguna langsung melihat file PDF
        if sys.platform == "darwin" and os.path.exists(out_dir):
            print(f"📂 Membuka folder hasil download di Finder...")
            os.system(f'open "{os.path.abspath(out_dir)}"')

    # Opsi 2: Download 1 Dokumen dari Link URL
    elif choice == "2":
        input_url = input("\n🔗 Masukkan link dokumen Scribd: ").strip()
        if not input_url:
            print("❌ Link tidak boleh kosong.")
            return

        default_out = os.path.expanduser("~/Downloads/Scribd")
        folder_prompt = input(
            "📁 Simpan file ke folder mana? [tekan Enter untuk '~/Downloads/Scribd']: "
        ).strip()
        out_dir = os.path.expanduser(folder_prompt) if folder_prompt else default_out

        try:
            saved_path, _ = download_scribd_document(
                input_url,
                output_dir=out_dir,
                close_driver=True,
            )
            if sys.platform == "darwin" and os.path.exists(out_dir):
                os.system(f'open "{os.path.abspath(out_dir)}"')
        except (RuntimeError, WebDriverException, ValueError) as error:
            print(f"Export failed: {error}")
            sys.exit(1)

    # Opsi 3: Bulk Download dari file teks (urls.txt)
    elif choice == "3":
        default_file = "urls.txt"
        file_input = input(
            f"\n📄 Masukkan nama file daftar URL [tekan Enter untuk '{default_file}']: "
        ).strip()
        filepath = file_input if file_input else default_file

        try:
            urls = load_urls_from_file(filepath)
        except Exception as error:
            print(f"❌ Error: {error}")
            return

        print(f"Berhasil membaca {len(urls)} URL dari {filepath}")
        default_out = os.path.expanduser("~/Downloads/Scribd")
        folder_prompt = input(
            "📁 Simpan file ke folder mana? [tekan Enter untuk '~/Downloads/Scribd']: "
        ).strip()
        out_dir = os.path.expanduser(folder_prompt) if folder_prompt else default_out

        bulk_download_documents(urls, output_dir=out_dir, delay_between=args.delay)
        if sys.platform == "darwin" and os.path.exists(out_dir):
            os.system(f'open "{os.path.abspath(out_dir)}"')

    elif choice in ("0", "exit", "q"):
        print("Sampai jumpa!")
        return
    else:
        print("Pilihan tidak valid.")


if __name__ == "__main__":
    main()


