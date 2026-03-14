/**
 * Entry point – starts the Express server and initialises the database.
 *
 * DEPRECATED: This legacy Node.js IVR backend is superseded by the FastAPI
 * backend in /backend. Set LEGACY_IVR_ENABLED=true to run this service.
 */

if (process.env.LEGACY_IVR_ENABLED !== "true") {
  console.error(
    "\n╔══════════════════════════════════════════════════════════════╗\n" +
    "║  LEGACY IVR SERVICE IS DISABLED                             ║\n" +
    "║                                                              ║\n" +
    "║  This Node.js backend has been superseded by the FastAPI     ║\n" +
    "║  backend in /backend. To start the modern backend, run:      ║\n" +
    "║                                                              ║\n" +
    "║    docker compose up app                                     ║\n" +
    "║                                                              ║\n" +
    "║  If you MUST run this legacy service, set:                   ║\n" +
    "║    LEGACY_IVR_ENABLED=true                                   ║\n" +
    "╚══════════════════════════════════════════════════════════════╝\n"
  );
  process.exit(1);
}

console.warn(
  "WARNING: Running legacy Node.js IVR backend. " +
  "This service is deprecated — migrate to the FastAPI backend in /backend."
);

const app = require("./app");
const db = require("./db");
const config = require("./config");

async function main() {
  try {
    await db.initializeDatabase();
    console.log("Database initialised.");
  } catch (err) {
    console.warn(
      "Database initialisation skipped (connection may not be available):",
      err.message
    );
  }

  app.listen(config.port, () => {
    console.log(`Redline AI IVR server listening on port ${config.port}`);
  });
}

main();
