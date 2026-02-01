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

app.use(session({
    secret: 'dev_secret_odisha_hacker',
    resave: false,
    saveUninitialized: true
}));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

// AUTH
app.get('/api/check-auth', (req, res) => res.json({ loggedIn: !!req.session.loggedIn }));
app.post('/api/login', (req, res) => {
    const { username, password } = req.body;
    if (username === adminUser && password === adminPass) {
        req.session.loggedIn = true;
        return res.json({ success: true });
    }
    res.json({ success: false });
});

// ================= UPLOAD WITH SESSION ID =================
app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.session.loggedIn) return res.status(403).json({ success: false, message: "Unauthorized" });
    if (!req.file) return res.status(400).json({ success: false, message: "No file" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;

    try {
        console.log(`Getting Server for ${apiKey}...`);
        
        // 1. Get Upload Server
        const serverRes = await axios.get(`https://devuploads.com/api/upload/server?key=${apiKey}`);
        
        if (!serverRes.data || !serverRes.data.result) {
            throw new Error("API Key Error or Server Down");
        }
        
        const uploadUrl = serverRes.data.result;
        console.log(`Upload URL: ${uploadUrl}`);

        // 2. Extract sess_id from URL (Ye Step Zaroori Hai!)
        // URL usually looks like: https://s1.devuploads.com/cgi-bin/upload.cgi?sess_id=XYZ...
        let sessId = "";
        if (uploadUrl.includes('sess_id=')) {
            sessId = uploadUrl.split('sess_id=')[1].split('&')[0];
        }

        // 3. Prepare Form Data with Session ID
        const form = new FormData();
        form.append('key', apiKey);
        if (sessId) form.append('sess_id', sessId); // Yeh missing tha!
        form.append('upload_type', 'file');
        form.append('file', fs.createReadStream(filePath), { filename: originalName });

        // 4. Upload with Browser Headers
        const uploadRes = await axios.post(uploadUrl, form, {
            headers: { 
                ...form.getHeaders(),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            },
            maxContentLength: Infinity,
            maxBodyLength: Infinity
        });

        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);

        if (uploadRes.data && uploadRes.data.status === 200) {
            const fileCode = uploadRes.data.result[0].filecode;
            res.json({ success: true, link: `https://devuploads.com/${fileCode}` });
        } else {
            console.error("API Error:", uploadRes.data);
            res.json({ success: false, message: uploadRes.data.msg || "Upload Rejected" });
        }

    } catch (err) {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        console.error("Error:", err.message);
        res.status(500).json({ success: false, message: err.message });
    }
});

app.listen(port, () => console.log(`App running on ${port}`));
