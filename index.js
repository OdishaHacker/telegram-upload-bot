const express = require('express');
const multer = require('multer');
const axios = require('axios');
const FormData = require('form-data');
const session = require('express-session');
const fs = require('fs');
const path = require('path');

const app = express();
const upload = multer({ dest: 'uploads/' });

// ENV
const adminUser = process.env.ADMIN_USER || "Admin";
const adminPass = process.env.ADMIN_PASS || "12345";
const port = process.env.PORT || 5000;

// SESSION
app.use(session({
    secret: 'odisha_force_secret',
    resave: false,
    saveUninitialized: true
}));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

// AUTH
app.get('/api/check-auth', (req, res) => {
    res.json({ loggedIn: !!req.session.loggedIn });
});

app.post('/api/login', (req, res) => {
    const { username, password } = req.body;
    console.log("[LOGIN]", username);

    if (username === adminUser && password === adminPass) {
        req.session.loggedIn = true;
        console.log("✅ LOGIN SUCCESS");
        return res.json({ success: true });
    }

    console.log("❌ LOGIN FAILED");
    res.json({ success: false });
});

// UPLOAD (GOFILE)
app.post('/upload', upload.single('file'), async (req, res) => {
    console.log("\n========== NEW UPLOAD (GOFILE) ==========");

    if (!req.session.loggedIn)
        return res.status(403).json({ success: false, message: "Unauthorized" });

    if (!req.file)
        return res.status(400).json({ success: false, message: "No file selected" });

    console.log("📄 File:", req.file.originalname);
    console.log("📦 Size:", (req.file.size / 1048576).toFixed(2), "MB");

    try {
        console.log("➡️ Getting GoFile server...");
        const serverRes = await axios.get("https://api.gofile.io/getServer");

        if (serverRes.data.status !== "ok")
            throw new Error("GoFile server error");

        const server = serverRes.data.data.server;
        console.log("🌐 GoFile Server:", server);

        console.log("➡️ Uploading to GoFile...");
        const form = new FormData();
        form.append("file", fs.createReadStream(req.file.path), req.file.originalname);

        const uploadRes = await axios.post(
            `https://${server}.gofile.io/uploadFile`,
            form,
            { headers: form.getHeaders(), maxBodyLength: Infinity }
        );

        fs.unlinkSync(req.file.path);

        if (uploadRes.data.status !== "ok")
            throw new Error("GoFile upload failed");

        const link = uploadRes.data.data.downloadPage;
        console.log("✅ UPLOAD SUCCESS:", link);

        res.json({ success: true, link });

    } catch (err) {
        console.log("🔥 UPLOAD ERROR:", err.message);

        if (req.file && fs.existsSync(req.file.path))
            fs.unlinkSync(req.file.path);

        res.status(500).json({
            success: false,
            message: "GoFile upload failed"
        });
    }
});

app.listen(port, () => {
    console.log(`🚀 Odisha Upload Server running on ${port}`);
});
