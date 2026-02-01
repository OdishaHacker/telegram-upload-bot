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
    if (username === adminUser && password === adminPass) {
        req.session.loggedIn = true;
        return res.json({ success: true });
    }
    res.json({ success: false });
});

// ================= UPLOAD =================
app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.session.loggedIn)
        return res.status(403).json({ success: false, message: "Unauthorized" });

    if (!req.file)
        return res.status(400).json({ success: false, message: "No file selected" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;

    try {
        console.log("Step 1: Get upload server");

        // 1️⃣ Get Upload Server
        const serverRes = await axios.get(
            "https://devuploads.com/api/upload/server",
            { params: { key: apiKey } }
        );

        if (!serverRes.data?.result)
            throw new Error("Upload server not received");

        const uploadUrl = serverRes.data.result;

        // 2️⃣ Generate sess_id (IMPORTANT)
        const sessId = Math.random().toString(36).substring(2) + Date.now();

        const finalUrl = `${uploadUrl}?sess_id=${sessId}`;
        console.log("Uploading to:", finalUrl);

        // 3️⃣ FormData
        const form = new FormData();
        form.append("sess_id", sessId);
        form.append("file", fs.createReadStream(filePath), originalName);

        // 4️⃣ Upload
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

        fs.unlinkSync(filePath);

        // 5️⃣ Extract file code
        let fileCode = null;

        if (uploadRes.data?.filecode)
            fileCode = uploadRes.data.filecode;
        else if (uploadRes.data?.result?.[0]?.filecode)
            fileCode = uploadRes.data.result[0].filecode;

        if (!fileCode) {
            console.error("Unknown response:", uploadRes.data);
            return res.json({
                success: false,
                message: "Uploaded but file link not received"
            });
        }

        const link = `https://devuploads.com/${fileCode}`;
        console.log("SUCCESS:", link);

        res.json({ success: true, link });

    } catch (err) {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        console.error("UPLOAD ERROR:", err.response?.data || err.message);
        res.status(500).json({
            success: false,
            message: "Upload failed. Check logs."
        });
    }
});

app.listen(port, () => {
    console.log(`🚀 Odisha Upload Server running on ${port}`);
});
