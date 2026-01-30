const express = require('express');
const multer = require('multer');
const TelegramBot = require('node-telegram-bot-api');
const session = require('express-session');
const fs = require('fs');
const path = require('path');
const fetch = require('node-fetch'); // Naya import

const app = express();
const upload = multer({ dest: 'uploads/' });

// ================= ENV =================
const token = process.env.BOT_TOKEN;
const channelId = process.env.CHANNEL_ID;
const port = process.env.PORT || 5000;
const adminUser = process.env.ADMIN_USER || "admin";
const adminPass = process.env.ADMIN_PASS || "password";

// ================= LOCAL BOT API SERVER CONFIG =================
const bot = new TelegramBot(token, { 
    polling: false,
    baseApiUrl: "http://tg-server:8081" 
});

// ================= MIDDLEWARE =================
app.use(session({
    secret: 'super_secret_key_odisha',
    resave: false,
    saveUninitialized: true
}));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ================= STATIC =================
const publicPath = path.join(__dirname, 'public');
const rootPath = __dirname;

if (fs.existsSync(path.join(publicPath, 'index.html'))) {
    app.use(express.static(publicPath));
} else {
    app.use(express.static(rootPath));
}

app.get('/', (req, res) => {
    let htmlFile = path.join(publicPath, 'index.html');
    if (!fs.existsSync(htmlFile)) {
        htmlFile = path.join(rootPath, 'index.html');
    }
    res.sendFile(htmlFile);
});

// ================= AUTH =================
app.post('/api/login', (req, res) => {
    const { username, password } = req.body;
    if (username === adminUser && password === adminPass) {
        req.session.loggedIn = true;
        return res.json({ success: true });
    }
    res.json({ success: false, message: "Invalid Credentials" });
});

// ================= UPLOAD (50MB+ Supported) =================
app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.session.loggedIn) return res.status(403).json({ success: false, message: "Unauthorized" });
    if (!req.file) return res.status(400).json({ success: false, message: "No file uploaded" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;

    try {
        const msg = await bot.sendDocument(
            channelId,
            fs.createReadStream(filePath),
            {},
            { filename: originalName, contentType: req.file.mimetype }
        );

        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);

        const fileId = msg.document.file_id;
        const safeName = encodeURIComponent(originalName);
        const downloadLink = `${req.protocol}://${req.get('host')}/dl/${fileId}/${safeName}`;

        res.json({ success: true, link: downloadLink });

    } catch (err) {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        console.error("Upload Error:", err);
        res.status(500).json({ success: false, message: "Upload failed" });
    }
});

// ================= DOWNLOAD (PERMANENT FIX) =================
app.get('/dl/:file_id/:filename', async (req, res) => {
    try {
        const fileId = req.params.file_id;
        
        // 1. Bot ko pehle file ki details nikaalne dein
        const file = await bot.getFile(fileId);
        
        // Local mode mein humein server ka base address aur file_path ko sahi se jodna hota hai
        const localDownloadUrl = `http://tg-server:8081/file/bot${token}/${file.file_path.replace(/^\//, '')}`;

        console.log("Attempting to fetch from:", localDownloadUrl);

        // 3. File fetch karein
        const response = await fetch(localDownloadUrl);
        
        if (!response.ok) {
            console.error(`Local Server Error: ${response.status} ${response.statusText}`);
            throw new Error("File not found on local server");
        }

        // 4. Browser ke liye headers set karein
        res.setHeader('Content-Disposition', `attachment; filename="${decodeURIComponent(req.params.filename)}"`);
        res.setHeader('Content-Type', 'application/octet-stream');

        // 5. Data pipe (stream) karein
        response.body.pipe(res);

    } catch (err) {
        console.error("Download Error Details:", err.message);
        res.status(500).send("Download failed: " + err.message);
    }
});

app.listen(port, () => {
    console.log(`Server running on port ${port}`);
});
