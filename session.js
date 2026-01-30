const { TelegramClient } = require("telegram");
const { StringSession } = require("telegram/sessions");
const input = require("input");

const apiId = Number(process.env.TG_API_ID);
const apiHash = process.env.TG_API_HASH;

if (!apiId || !apiHash) {
  console.log("❌ TG_API_ID or TG_API_HASH missing");
  process.exit(1);
}

(async () => {
  const client = new TelegramClient(
    new StringSession(""),
    apiId,
    apiHash,
    { connectionRetries: 5 }
  );

  await client.start({
    phoneNumber: async () => input.text("📱 Phone number: "),
    phoneCode: async () => input.text("📩 OTP Code: "),
    password: async () => input.text("🔐 2FA Password (if any): "),
    onError: (err) => console.log(err)
  });

  console.log("\n==============================");
  console.log("✅ SESSION STRING (COPY THIS)");
  console.log("==============================\n");
  console.log(client.session.save());
  console.log("\n==============================\n");

  process.exit(0);
})();
