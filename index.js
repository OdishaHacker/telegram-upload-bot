const express = require('express');
const multer = require('multer');
const TelegramBot = require('node-telegram-bot-api');
const session = require('express-session');
const fs = require('fs');
const path = require('path');

const app = express();

// ================= MULTER (2GB LIMIT) =================
const upload = multer({
    dest: 'uploads/',
    limits: {
        fileSize: 2 * 1024 * 1024 * 1024 // ✅ 2GB
    }
});

// ================= ENV =================
const token = process.env.BOT_TOKEN;
const channelId = process.env.CHANNEL_ID;
const port = process.env.PORT || 5000;
const adminUser = process.env.ADMIN_USER || "admin";
const adminPass = process.env.ADMIN_PASS || "password";

// ================= TELEGRAM BOT =================
const bot = new TelegramBot(token, { polling: false });

// ================= SESSION =================
app.use(session({
    name: 'odisha-session',
    secret: 'super_secret_key_odisha',
    resave: false,
    saveUninitialized: false,
    cookie: {
        httpOnly: true,
        sameSite: 'lax'
    }
}));

// ================= BODY =================
app.use(express.json({ limit: '2gb' }));
app.use(express.urlencoded({ extended: true, limit: '2gb' }));

// ================= STATIC =================
app.use(express.static(path.join(__dirname, 'public')));

// ================= AUTH CHECK =================
app.get('/api/check-auth', (req, res) => {
    res.json({ loggedIn: !!req.session.loggedIn });
});

// ================= LOGIN =================
app.post('/api/login', (req, res) => {
    const { username, password } = req.body;
    if (username === adminUser && password === adminPass) {
        req.session.loggedIn = true;
        return res.json({ success: true });
    }
    res.json({ success: false });
});

// ================= UPLOAD (2GB SAFE) =================
app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.session.loggedIn)
        return res.status(403).json({ success: false, message: "Not logged in" });

    if (!req.file)
        return res.status(400).json({ success: false, message: "No file" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;

    try {
        const msg = await bot.sendDocument(
            channelId,
            fs.createReadStream(filePath),
            {},
            { filename: originalName }
        );

        fs.unlinkSync(filePath);

        const fileId = msg.document.file_id;
        const safeName = encodeURIComponent(originalName);
        const link = `${req.protocol}://${req.get('host')}/dl/${fileId}/${safeName}`;

        res.json({ success: true, link });

    } catch (err) {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        res.status(500).json({ success: false, message: "Telegram upload failed" });
    }
});

// ================= DOWNLOAD (NO LIMIT) =================
app.get('/dl/:file_id/:filename', async (req, res) => {
    try {
        const file = await bot.getFile(req.params.file_id);
        const tgUrl = `https://api.telegram.org/file/bot${token}/${file.file_path}`;

        const https = require('https');

        res.setHeader(
            'Content-Disposition',
            `attachment; filename="${decodeURIComponent(req.params.filename)}"`
        );
        res.setHeader('Content-Type', 'application/octet-stream');

        https.get(tgUrl, tgRes => {
            tgRes.pipe(res);
        }).on('error', () => {
            res.status(500).send("Download failed");
        });

    } catch (err) {
        res.status(500).send("Download failed");
    }
});

// ================= START =================
app.listen(port, '0.0.0.0', () => {
    console.log("Server running on port", port);
});
