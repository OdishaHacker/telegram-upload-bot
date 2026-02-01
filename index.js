const express = require("express");
const multer = require("multer");
const axios = require("axios");
const FormData = require("form-data");
const session = require("express-session");
const fs = require("fs");
const path = require("path");

const app = express();
const upload = multer({ dest: "uploads/" });

const ADMIN_USER = process.env.ADMIN_USER || "Admin";
const ADMIN_PASS = process.env.ADMIN_PASS || "12345";
const PORT = process.env.PORT || 5000;

// ================= SESSION =================
app.use(
  session({
    secret: "odisha_gofile_secret",
    resave: false,
    saveUninitialized: true,
  })
);

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, "public")));

// ================= AUTH =================
app.get("/api/check-auth", (req, res) => {
  res.json({ loggedIn: !!req.session.loggedIn });
});

app.post("/api/login", (req, res) => {
  const { username, password } = req.body;
  console.log("[LOGIN]", username);

  if (username === ADMIN_USER && password === ADMIN_PASS) {
    req.session.loggedIn = true;
    console.log("✅ LOGIN SUCCESS");
    return res.json({ success: true });
  }

  console.log("❌ LOGIN FAILED");
  res.json({ success: false });
});

// ================= UPLOAD (GOFILE) =================
app.post("/upload", upload.single("file"), async (req, res) => {
  if (!req.session.loggedIn)
    return res.status(403).json({ success: false, message: "Unauthorized" });

  if (!req.file)
    return res.status(400).json({ success: false, message: "No file selected" });

  const filePath = req.file.path;
  const originalName = req.file.originalname;
  const fileSizeMB = (req.file.size / 1048576).toFixed(2);

  console.log("\n========== NEW UPLOAD (GOFILE) ==========");
  console.log("📄 File:", originalName);
  console.log("📦 Size:", fileSizeMB, "MB");

  try {
    console.log("➡️ Uploading to GoFile global endpoint...");

    const form = new FormData();
    form.append("file", fs.createReadStream(filePath), originalName);

    const uploadRes = await axios.post(
      "https://upload.gofile.io/uploadfile",
      form,
      {
        headers: {
          ...form.getHeaders(),
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
        },
        maxBodyLength: Infinity,
        maxContentLength: Infinity,
      }
    );

    fs.unlinkSync(filePath);

    console.log("🌐 GoFile RESPONSE:", uploadRes.data);

    if (uploadRes.data.status !== "ok") {
      throw new Error("GoFile upload failed");
    }

    const downloadLink = uploadRes.data.data.downloadPage;

    console.log("✅ UPLOAD SUCCESS:", downloadLink);

    res.json({
      success: true,
      link: downloadLink,
      size: fileSizeMB,
      name: originalName,
    });
  } catch (err) {
    if (fs.existsSync(filePath)) fs.unlinkSync(filePath);

    console.error("🔥 UPLOAD ERROR:", err.message);
    res.status(500).json({
      success: false,
      message: err.message,
    });
  }
});

app.listen(PORT, () => {
  console.log(`🚀 Odisha Upload Server running on ${PORT}`);
});
