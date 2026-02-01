const express = require('express');
const multer = require('multer');
const axios = require('axios');
const FormData = require('form-data');
const session = require('express-session');
const fs = require('fs');
const path = require('path');

const app = express();
const upload = multer({ dest: 'uploads/' });

// ================= ENV =================
const apiKey = process.env.DEVUPLOADS_API_KEY;
const adminUser = process.env.ADMIN_USER || "Admin";
const adminPass = process.env.ADMIN_PASS || "12345";
const port = process.env.PORT || 5000;

// ================= SESSION =================
app.use(session({
    secret: 'odisha_force_secret',
    resave: false,
    saveUninitialized: true
}));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

// ================= AUTH =================
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

// ================= UPLOAD =================
app.post('/upload', upload.single('file'), async (req, res) => {
    console.log("\n========== NEW UPLOAD ==========");

    if (!req.session.loggedIn)
        return res.status(403).json({ success: false, message: "Unauthorized" });

    if (!req.file)
        return res.status(400).json({ success: false, message: "No file selected" });

    console.log("📄 File Name:", req.file.originalname);
    console.log("📦 File Size:", (req.file.size / 1048576).toFixed(2), "MB");

    try {
        // STEP 1: GET UPLOAD SERVER + SESSION ID
        console.log("➡️ Step 1: Getting upload server...");
        const serverRes = await axios.get(
            "https://devuploads.com/api/upload/server",
            { params: { key: apiKey } }
        );

        console.log("🌐 API RESPONSE:", serverRes.data);

        const uploadUrl = serverRes.data.result;

        // 🔴 IMPORTANT NOTE:
        // sess_id RANDOM NAHI BANAANA
        // API JO sess_id DE → WAHI USE KARNA
        const sessId = serverRes.data.sess_id;

        if (!uploadUrl || !sessId)
            throw new Error("Upload URL or sess_id missing from API");

        const finalUrl = `${uploadUrl}?sess_id=${sessId}`;
        console.log("➡️ Uploading to:", finalUrl);

        // STEP 2: FORM DATA
        const form = new FormData();
        form.append("sess_id", sessId);
        form.append(
            "file",
            fs.createReadStream(req.file.path),
            req.file.originalname
        );

        // STEP 3: UPLOAD
        const uploadRes = await axios.post(finalUrl, form, {
            headers: {
                ...form.getHeaders(),
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://devuploads.com/",
                "Origin": "https://devuploads.com"
            },
            maxBodyLength: Infinity,
            maxContentLength: Infinity
        });

        console.log("📨 UPLOAD RESPONSE:", uploadRes.data);

        if (fs.existsSync(req.file.path))
            fs.unlinkSync(req.file.path);

        // STEP 4: PARSE RESULT
        const fileCode =
            uploadRes.data?.filecode ||
            uploadRes.data?.result?.[0]?.filecode;

        if (!fileCode) {
            console.log("❌ File code missing");
            return res.json({
                success: false,
                message: "Upload failed (no file code)"
            });
        }

        const link = `https://devuploads.com/${fileCode}`;
        console.log("✅ UPLOAD SUCCESS:", link);

        res.json({ success: true, link });

    } catch (err) {
        console.log("🔥 UPLOAD ERROR:", err.response?.data || err.message);

        if (req.file && fs.existsSync(req.file.path))
            fs.unlinkSync(req.file.path);

        res.status(500).json({
            success: false,
            message: "Upload failed (check server logs)"
        });
    }
});

app.listen(port, () => {
    console.log(`🚀 Odisha Upload Server running on ${port}`);
});
