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
// Coolify Environment Variables se ye values uthayega
const apiKey = process.env.DEVUPLOADS_API_KEY; 
const adminUser = process.env.ADMIN_USER || "admin";
const adminPass = process.env.ADMIN_PASS || "password";
const port = process.env.PORT || 5000;

// ================= MIDDLEWARE =================
app.use(session({
    secret: 'dev_secret_odisha_hacker',
    resave: false,
    saveUninitialized: true
}));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// ================= STATIC FILES =================
const publicPath = path.join(__dirname, 'public');
app.use(express.static(publicPath));

app.get('/', (req, res) => {
    res.sendFile(path.join(publicPath, 'index.html'));
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

// ================= UPLOAD TO DEVUPLOADS =================
app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.session.loggedIn) return res.status(403).json({ success: false, message: "Unauthorized" });
    if (!req.file) return res.status(400).json({ success: false, message: "No file selected" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;

    try {
        // 1. DevUploads se active upload server mangna
        const serverRes = await axios.get(`https://devuploads.com/api/upload/server?key=${apiKey}`);
        if (!serverRes.data || !serverRes.data.result) throw new Error("Could not get upload server");
        
        const uploadUrl = serverRes.data.result;

        // 2. Upload ke liye form data taiyar karna
        const form = new FormData();
        form.append('key', apiKey);
        form.append('file', fs.createReadStream(filePath), { filename: originalName });

        // 3. DevUploads server par file bhejna
        console.log(`Uploading ${originalName} to DevUploads...`);
        const uploadRes = await axios.post(uploadUrl, form, {
            headers: { ...form.getHeaders() },
            maxContentLength: Infinity,
            maxBodyLength: Infinity
        });

        // Local temporary file delete karna space bachane ke liye
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);

        if (uploadRes.data && uploadRes.data.status === 200) {
            const fileCode = uploadRes.data.result[0].filecode;
            const downloadUrl = `https://devuploads.com/${fileCode}`;
            
            console.log("Upload Success:", downloadUrl);
            res.json({ success: true, link: downloadUrl });
        } else {
            throw new Error(uploadRes.data.msg || "Upload failed on DevUploads side");
        }

    } catch (err) {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        console.error("Upload Error:", err.message);
        res.status(500).json({ success: false, message: "Error: " + err.message });
    }
});

// ================= START SERVER =================
app.listen(port, () => {
    console.log(`DevUpload Bot is live on port ${port}`);
});
