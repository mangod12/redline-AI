require("dotenv").config();

module.exports = {
  port: process.env.PORT || 3000,
  database: {
    connectionString: process.env.DATABASE_URL,
  },
  twilio: {
    accountSid: process.env.TWILIO_ACCOUNT_SID,
    authToken: process.env.TWILIO_AUTH_TOKEN,
    phoneNumber: process.env.TWILIO_PHONE_NUMBER,
  },
  apiKey: process.env.API_KEY,
  google: {
    projectId: process.env.GOOGLE_PROJECT_ID,
    credentials: process.env.GOOGLE_APPLICATION_CREDENTIALS,
  },
};
