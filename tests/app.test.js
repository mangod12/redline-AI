const request = require("supertest");
const app = require("../src/app");

// ── Mock the ivr module ────────────────────────────────────────────
jest.mock("../src/ivr", () => ({
  buildGreetingTwiml: jest.fn(
    (baseUrl) =>
      `<?xml version="1.0" encoding="UTF-8"?><Response><Say>Greeting</Say></Response>`
  ),
  processCall: jest.fn(async (input) => ({
    id: "00000000-0000-0000-0000-000000000001",
    callerNumber: input.callerNumber || "unknown",
    transcript: "Help there is a fire",
    severity: "high",
    responder: "fire",
    status: "pending",
    summary: "Fire emergency reported",
  })),
}));

// ── Mock the db module ─────────────────────────────────────────────
jest.mock("../src/db", () => ({
  listCalls: jest.fn(async () => [
    {
      id: "00000000-0000-0000-0000-000000000001",
      caller_number: "+15551234567",
      severity: "high",
      responder: "fire",
      status: "pending",
    },
  ]),
  getCallById: jest.fn(async (id) => {
    if (id === "00000000-0000-0000-0000-000000000001") {
      return {
        id,
        caller_number: "+15551234567",
        severity: "high",
        responder: "fire",
        status: "pending",
      };
    }
    return null;
  }),
  updateCallStatus: jest.fn(async (id, status) => {
    if (id === "00000000-0000-0000-0000-000000000001") {
      return {
        id,
        caller_number: "+15551234567",
        severity: "high",
        responder: "fire",
        status,
      };
    }
    return null;
  }),
}));

// ── Tests ──────────────────────────────────────────────────────────

describe("GET /health", () => {
  it("returns 200 with service status", async () => {
    const res = await request(app).get("/health");
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: "ok", service: "redline-ai-ivr" });
  });
});

describe("POST /api/calls/incoming", () => {
  it("returns TwiML XML greeting", async () => {
    const res = await request(app)
      .post("/api/calls/incoming")
      .send({ From: "+15551234567" });
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toMatch(/xml/);
    expect(res.text).toContain("<Response>");
  });
});

describe("POST /api/calls/handle-recording", () => {
  it("processes a recording and returns TwiML confirmation", async () => {
    const res = await request(app)
      .post("/api/calls/handle-recording")
      .type("form")
      .send({
        From: "+15551234567",
        RecordingUrl: "https://api.twilio.com/recordings/RE123",
      });
    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toMatch(/xml/);
    expect(res.text).toContain("Your emergency has been logged");
    expect(res.text).toContain("fire");
  });
});

describe("POST /api/calls", () => {
  it("creates a new call record and returns 201", async () => {
    const res = await request(app).post("/api/calls").send({
      callerNumber: "+15559876543",
      audio: "base64audiocontent",
      latitude: 40.7128,
      longitude: -74.006,
    });
    expect(res.status).toBe(201);
    expect(res.body).toHaveProperty("id");
    expect(res.body).toHaveProperty("responder", "fire");
    expect(res.body).toHaveProperty("severity", "high");
  });
});

describe("GET /api/calls", () => {
  it("returns a list of calls", async () => {
    const res = await request(app).get("/api/calls");
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body)).toBe(true);
    expect(res.body.length).toBeGreaterThan(0);
  });

  it("passes query filters to the db layer", async () => {
    const db = require("../src/db");
    await request(app).get("/api/calls?severity=high&responder=fire&limit=10&offset=5");
    expect(db.listCalls).toHaveBeenCalledWith({
      severity: "high",
      responder: "fire",
      limit: 10,
      offset: 5,
    });
  });
});

describe("GET /api/calls/:id", () => {
  it("returns a single call by ID", async () => {
    const res = await request(app).get(
      "/api/calls/00000000-0000-0000-0000-000000000001"
    );
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty("id", "00000000-0000-0000-0000-000000000001");
  });

  it("returns 404 for a non-existent call", async () => {
    const res = await request(app).get(
      "/api/calls/00000000-0000-0000-0000-999999999999"
    );
    expect(res.status).toBe(404);
    expect(res.body).toHaveProperty("error", "Call not found");
  });
});

describe("PATCH /api/calls/:id/status", () => {
  it("updates the status of a call", async () => {
    const res = await request(app)
      .patch("/api/calls/00000000-0000-0000-0000-000000000001/status")
      .send({ status: "dispatched" });
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty("status", "dispatched");
  });

  it("rejects an invalid status value", async () => {
    const res = await request(app)
      .patch("/api/calls/00000000-0000-0000-0000-000000000001/status")
      .send({ status: "invalid" });
    expect(res.status).toBe(400);
    expect(res.body).toHaveProperty("error", "Invalid status");
  });

  it("returns 404 when call does not exist", async () => {
    const res = await request(app)
      .patch("/api/calls/00000000-0000-0000-0000-999999999999/status")
      .send({ status: "resolved" });
    expect(res.status).toBe(404);
    expect(res.body).toHaveProperty("error", "Call not found");
  });
});
