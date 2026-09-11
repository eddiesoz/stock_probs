// This fixture records application-data traffic so every journey can enforce the API-only boundary.
const base = require("@playwright/test");

exports.expect = base.expect;
exports.test = base.test.extend({
  applicationRequests: async ({ page }, use) => {
    const requests = [];
    page.on("request", (request) => {
      if (["fetch", "xhr"].includes(request.resourceType())) requests.push(request.url());
    });
    await use(requests);
  },
});
