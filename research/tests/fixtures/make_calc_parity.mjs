// Membuat fixture kesetaraan calc.js ↔ solcoat_research/calculator.py.
// Pakai: node make_calc_parity.mjs <path ke src/utils/calc.js> > calc_js_parity.json
import { pathToFileURL } from 'node:url';

const calcPath = process.argv[2];
if (!calcPath) {
    console.error('Usage: node make_calc_parity.mjs <path/to/calc.js>');
    process.exit(2);
}
const { calculateEstimations } = await import(pathToFileURL(calcPath).href);

const RATES = { USD: 1, IDR: 17788, EUR: 0.86453 };
const base = {
    operationHours: 8760, heaterEfficiency: 85, exchangeRates: RATES,
    scenarios: [2.5, 5, 7], scenarioLabels: ['minimum', 'mostLikely', 'ideal'],
    basisData: {}, costs: { marketPrice: 10, marketPriceCurrency: 'USD', coatingMode: 'estimated' },
};
const merge = (over) => ({
    ...base, ...over,
    basisData: { ...base.basisData, ...(over.basisData || {}) },
    costs: { ...base.costs, ...(over.costs || {}) },
});

const cases = {
    fo_direct_701H1: merge({
        fuelType: 'fo',
        basisData: { directValue: 230.27, directUnit: 'GJ/hr' },
        costs: { actualPrice: 28, actualPriceCurrency: 'USD', coatingEstPrice: 20600000, coatingEstCurrency: 'IDR',
                 coatingAreaFiber: 800 },
    }),
    ng_design_duty: merge({
        fuelType: 'ng', heaterEfficiency: 88,
        basisData: { designDuty: 45, designUnit: 'MMBtu/hr' },
        costs: { actualPrice: 7, actualPriceCurrency: 'USD', coatingEstPrice: 85000000, coatingEstCurrency: 'IDR',
                 coatingAreaCastable: 463, coatingAreaFiber: 120 },
    }),
    ng_fuel_rate_nm3: merge({
        fuelType: 'ng', operationHours: 8000,
        basisData: { fuelRate: 24888, fuelRateUnit: 'Nm3/hr', feedRate: 120, feedRateUnit: 'm3/hr' },
        costs: { coatingEstPrice: 5000, coatingEstCurrency: 'USD', coatingAreaCastable: 1514 },
    }),
    lpg_kg_rate_market_fallback: merge({
        fuelType: 'lpg',
        basisData: { fuelRate: 1500, fuelRateUnit: 'kg/hr', feedRate: 30 },
        costs: { coatingEstPrice: 85000000, coatingEstCurrency: 'IDR', coatingAreaCastable: 10, includeTubeCoating: true,
                 tubeCoatingGallons: 4 },
    }),
    refinery_gas_mt_price: merge({
        fuelType: 'refinery',
        basisData: { directValue: 55, directUnit: 'Gcal/hr' },
        costs: { marketPrice: 450, marketPriceCurrency: 'USD', fuelPriceUnit: 'MT', coatingEstPrice: 85000000,
                 coatingEstCurrency: 'IDR', coatingAreaCastable: 350 },
    }),
    mixed_composition_kcal: merge({
        fuelType: 'mixed', lhvUnit: 'kcal/kg',
        fuelComposition: [
            { name: 'LPG', percentage: 70, lhv: 11000, price: 12.5 },
            { name: 'Fuel Oil', percentage: 30, lhv: 9800, price: 10 },
        ],
        basisData: { fuelRate: 2000, fuelRateUnit: 'kg/hr' },
        costs: { actualPriceCurrency: 'USD', coatingEstPrice: 6000, coatingEstCurrency: 'USD', coatingAreaFiber: 250 },
    }),
    mixed_volumetric_custom: merge({
        fuelType: 'mixed', lhvUnit: 'GJ/Nm3', customLHV: 0.038,
        basisData: { fuelRate: 900, fuelRateUnit: 'kg/hr' },
        costs: { actualPrice: 9, actualPriceCurrency: 'USD', coatingEstPrice: 6000, coatingEstCurrency: 'USD',
                 coatingAreaCastable: 90 },
    }),
    fixed_cost_eur: merge({
        fuelType: 'fo',
        basisData: { directValue: 30, directUnit: 'Gcal/hr' },
        costs: { actualPrice: 600, actualPriceCurrency: 'USD', fuelPriceUnit: 'MT', coatingMode: 'fixed',
                 coatingCost: 250000, coatingCostCurrency: 'EUR' },
    }),
    no_coating_cost: merge({
        fuelType: 'ng',
        basisData: { directValue: 10, directUnit: 'GJ/hr' },
        costs: { actualPrice: 6.5, actualPriceCurrency: 'USD' },
    }),
};

const output = {};
for (const [name, inputs] of Object.entries(cases)) {
    output[name] = { inputs, result: calculateEstimations(inputs) };
}
console.log(JSON.stringify(output, null, 2));
