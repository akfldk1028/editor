const config = require('./playwright.migration.config.cjs');
module.exports = { ...config, testMatch: ['product-navigation.spec.cjs'] };
