/**
 * Express application – API routes for the Redline AI IVR system.
 */
const express = require("express");
const ivr = require("./ivr");
const db = require("./db");

const PUBLIC_BASE_URL = process.env.PUBLIC_BASE_URL || "";

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ---- Twilio webhook signature validation ----
const twilio = require("twilio");
const config = require("./config");

function validateTwilioWebhook(req, res, next) {
  if (!config.twilio.authToken) {
    console.warn("TWILIO_AUTH_TOKEN not set - skipping signature validation");
    return next();
  }
  const signature = req.headers["x-twilio-signature"] || "";
  const url = `${req.protocol}://${req.get("host")}${req.originalUrl}`;
  const valid = twilio.validateRequest(
    config.twilio.authToken,
    signature,
    url,
    req.body
  );
  if (!valid) {
    return res.status(403).json({ error: "Invalid Twilio signature" });
  }
  next();
}

/**
 * Simple API key authentication for REST endpoints.
 * Set API_KEY env var. If not set, all requests are rejected in production.
 */
function requireApiKey(req, res, next) {
  const apiKey = process.env.API_KEY;
  if (!apiKey) {
    // In development without API_KEY set, allow requests with a warning
    if (process.env.NODE_ENV !== "production") {
      return next();
    }
    return res.status(503).json({ error: "API_KEY not configured" });
  }
  const provided = req.headers["x-api-key"] || req.query.api_key;
  if (!provided || provided !== apiKey) {
    return res.status(401).json({ error: "Invalid or missing API key" });
  }
  next();
}

// ──── Health check ────────────────────────────────────────────────
app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "redline-ai-ivr" });
});

// ──── Twilio webhook – initial call ───────────────────────────────
app.post("/api/calls/incoming", validateTwilioWebhook, (req, res) => {
  const baseUrl = PUBLIC_BASE_URL || `${req.protocol}://${req.get("host")}`;
  res.type("text/xml").send(ivr.buildGreetingTwiml(baseUrl));
});

// ──── Twilio webhook – recording completed ────────────────────────
app.post("/api/calls/handle-recording", validateTwilioWebhook, async (req, res) => {
  try {
    const { From: callerNumber, RecordingUrl, Latitude, Longitude } = req.body;

    const record = await ivr.processCall({
      callerNumber: callerNumber || "unknown",
      audio: RecordingUrl || "",
      latitude: Latitude ? parseFloat(Latitude) : undefined,
      longitude: Longitude ? parseFloat(Longitude) : undefined,
    });

    // Respond with TwiML confirming dispatch
    res.type("text/xml").send(`<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Your emergency has been logged. ${record.responder} services are being dispatched. Your reference number is ${record.id}.</Say>
</Response>`);
  } catch (err) {
    console.error("Error processing recording:", err);
    res.type("text/xml").send(`<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">We encountered an error processing your call. Please stay on the line.</Say>
</Response>`);
  }
});

// ──── REST API – manual call submission (for testing / integrations) ──
app.post("/api/calls", requireApiKey, async (req, res) => {
  try {
    const record = await ivr.processCall(req.body);
    res.status(201).json(record);
  } catch (err) {
    console.error("Error creating call:", err);
    res.status(500).json({ error: "Failed to process call" });
  }
});

// ──── REST API – list calls (with optional filters) ───────────────
app.get("/api/calls", requireApiKey, async (req, res) => {
  try {
    const calls = await db.listCalls({
      severity: req.query.severity,
      responder: req.query.responder,
      limit: req.query.limit ? parseInt(req.query.limit, 10) : undefined,
      offset: req.query.offset ? parseInt(req.query.offset, 10) : undefined,
    });
    res.json(calls);
  } catch (err) {
    console.error("Error listing calls:", err);
    res.status(500).json({ error: "Failed to list calls" });
  }
});

// ──── REST API – get single call ──────────────────────────────────
app.get("/api/calls/:id", requireApiKey, async (req, res) => {
  try {
    const call = await db.getCallById(req.params.id);
    if (!call) return res.status(404).json({ error: "Call not found" });
    res.json(call);
  } catch (err) {
    console.error("Error fetching call:", err);
    res.status(500).json({ error: "Failed to fetch call" });
  }
});

// ──── REST API – update call status ───────────────────────────────
app.patch("/api/calls/:id/status", requireApiKey, async (req, res) => {
  try {
    const { status } = req.body;
    if (!["pending", "dispatched", "resolved"].includes(status)) {
      return res.status(400).json({ error: "Invalid status" });
    }
    const call = await db.updateCallStatus(req.params.id, status);
    if (!call) return res.status(404).json({ error: "Call not found" });
    res.json(call);
  } catch (err) {
    console.error("Error updating call status:", err);
    res.status(500).json({ error: "Failed to update status" });
  }
});

module.exports = app;
