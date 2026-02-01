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
    res.json({ success: false, message: "Invalid Credentials" });
});

// ================= UPLOAD WITH DETAILED ERROR =================
app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.session.loggedIn) return res.status(403).json({ success: false, message: "Unauthorized: Please Login" });
    if (!req.file) return res.status(400).json({ success: false, message: "No file selected" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;

    try {
        // 1. Get Upload Server
        const serverRes = await axios.get(`https://devuploads.com/api/upload/server?key=${apiKey}`);
        if (!serverRes.data || !serverRes.data.result) {
            throw new Error(`API Key Issue or DevUploads Server Down: ${JSON.stringify(serverRes.data)}`);
        }
        
        const uploadUrl = serverRes.data.result;

        // 2. Prepare Form Data
        const form = new FormData();
        form.append('key', apiKey);
        form.append('file', fs.createReadStream(filePath), { filename: originalName });

        // 3. Upload to DevUploads
        const uploadRes = await axios.post(uploadUrl, form, {
            headers: { ...form.getHeaders() },
            maxContentLength: Infinity,
            maxBodyLength: Infinity
        });

        // Cleanup local file
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);

        if (uploadRes.data && uploadRes.data.status === 200) {
            const fileCode = uploadRes.data.result[0].filecode;
            res.json({ success: true, link: `https://devuploads.com/${fileCode}` });
        } else {
            // API side error message
            const apiError = uploadRes.data.msg || "Unknown API Error";
            throw new Error(apiError);
        }

    } catch (err) {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        
        // Detailed error for frontend
        let errorMsg = err.message;
        if (err.response && err.response.data) {
            errorMsg = JSON.stringify(err.response.data);
        }

        console.error("UPLOAD ERROR:", errorMsg);
        res.status(500).json({ success: false, message: errorMsg });
    }
});

app.listen(port, () => console.log(`Server running on port ${port}`));
