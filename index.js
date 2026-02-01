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
    secret: 'dev_secret_odisha_final',
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

// ================= UPLOAD (FIXED JSON LOGIC) =================
app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.session.loggedIn) return res.status(403).json({ success: false, message: "Unauthorized" });
    if (!req.file) return res.status(400).json({ success: false, message: "No file" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;

    try {
        console.log(`Step 1: Fetching Server for Key: ${apiKey.substring(0, 5)}...`);
        
        // 1. Get Server JSON
        const serverRes = await axios.get(`https://devuploads.com/api/upload/server?key=${apiKey}`);
        
        if (!serverRes.data || !serverRes.data.result) {
            throw new Error("Failed to get server info from API");
        }

        // 🛠️ YAHAN THI GALTI - AB THEEK HAI
        // URL se nahi, balki direct JSON property se ID nikalo
        const uploadUrl = serverRes.data.result;
        const sessId = serverRes.data.sess_id; // Ye raha asli sess_id!

        console.log(`URL: ${uploadUrl}`);
        console.log(`Session ID: ${sessId}`); // Ab ye print hoga!

        if (!sessId) {
             throw new Error("Session ID not found in API response!");
        }

        // 2. Prepare Form Data
        const form = new FormData();
        form.append('key', apiKey);
        form.append('sess_id', sessId); // Ab ye sahi se jayega
        form.append('upload_type', 'file');
        
        form.append('file', fs.createReadStream(filePath), { 
            filename: originalName,
            contentType: req.file.mimetype
        });

        // 3. Send with Browser Headers
        const uploadRes = await axios.post(uploadUrl, form, {
            headers: { 
                ...form.getHeaders(),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
            maxContentLength: Infinity,
            maxBodyLength: Infinity
        });

        // Cleanup
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);

        // 4. Handle Response
        if (uploadRes.data && uploadRes.status === 200) {
            // Kabhi kabhi array aata hai, kabhi object
            let fileCode = "";
            if (uploadRes.data.filecode) fileCode = uploadRes.data.filecode;
            else if (Array.isArray(uploadRes.data) && uploadRes.data[0]) fileCode = uploadRes.data[0].file_code;
            else if (uploadRes.data.result && uploadRes.data.result[0]) fileCode = uploadRes.data.result[0].filecode;

            if (fileCode) {
                res.json({ success: true, link: `https://devuploads.com/${fileCode}` });
            } else {
                console.error("Link Missing in Response:", uploadRes.data);
                res.json({ success: false, message: "Upload success but no link found." });
            }
        } else {
            res.json({ success: false, message: "Upload Failed via API" });
        }

    } catch (err) {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        
        let errorMsg = err.message;
        if (err.response) {
            console.error("Server Error HTML:", err.response.data); // Asli error yahan dikhega
            errorMsg = `Server Error ${err.response.status}`;
        }
        console.error("Upload Failed:", errorMsg);
        res.status(500).json({ success: false, message: errorMsg });
    }
});

app.listen(port, () => console.log(`Fixed Bot running on ${port}`));
