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
    secret: 'dev_secret_odisha_force',
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

// ================= UPLOAD (FORCE AUTH MODE) =================
app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.session.loggedIn) return res.status(403).json({ success: false, message: "Unauthorized" });
    if (!req.file) return res.status(400).json({ success: false, message: "No file" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;

    try {
        console.log(`Step 1: Getting Server...`);
        
        // 1. Get Server JSON
        const serverRes = await axios.get(`https://devuploads.com/api/upload/server?key=${apiKey}`);
        
        if (!serverRes.data || !serverRes.data.result) {
            throw new Error("Failed to get server info from API");
        }

        const uploadUrl = serverRes.data.result;
        const sessId = serverRes.data.sess_id;

        console.log(`Session ID Found: ${sessId}`);

        if (!sessId) throw new Error("Session ID missing in API response");

        // 2. FORCE URL (URL mein ID jodna zaroori hai)
        // Agar URL mein pehle se ? hai to & lagao, nahi to ? lagao
        const finalUrl = uploadUrl.includes('?') 
            ? `${uploadUrl}&sess_id=${sessId}` 
            : `${uploadUrl}?sess_id=${sessId}`;
            
        console.log(`Uploading to: ${finalUrl}`);

        // 3. Prepare Form Data
        const form = new FormData();
        // Form mein bhi ID daal dete hain (Double safety)
        form.append('sess_id', sessId);
        form.append('upload_type', 'file');
        form.append('file', fs.createReadStream(filePath), { 
            filename: originalName,
            contentType: req.file.mimetype
        });

        // 4. Send with Real Browser Headers
        const uploadRes = await axios.post(finalUrl, form, {
            headers: { 
                ...form.getHeaders(),
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://devuploads.com/',
                'Origin': 'https://devuploads.com'
            },
            maxContentLength: Infinity,
            maxBodyLength: Infinity
        });

        // Cleanup
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);

        // 5. Response Check
        if (uploadRes.data && uploadRes.status === 200) {
            let fileCode = "";
            // Response format handle karna
            if (uploadRes.data.filecode) fileCode = uploadRes.data.filecode;
            else if (Array.isArray(uploadRes.data) && uploadRes.data[0]) fileCode = uploadRes.data[0].file_code;
            else if (uploadRes.data.result && uploadRes.data.result[0]) fileCode = uploadRes.data.result[0].filecode;

            if (fileCode) {
                console.log("Success! Code:", fileCode);
                res.json({ success: true, link: `https://devuploads.com/${fileCode}` });
            } else {
                console.error("No Link:", uploadRes.data);
                res.json({ success: false, message: "Upload accepted but link missing." });
            }
        } else {
            res.json({ success: false, message: "Upload Failed" });
        }

    } catch (err) {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        
        let errorMsg = err.message;
        if (err.response) {
            console.error("Server Error HTML:", err.response.data);
            errorMsg = `Server Error ${err.response.status} - Check Logs`;
        }
        res.status(500).json({ success: false, message: errorMsg });
    }
});

app.listen(port, () => console.log(`Force-Auth Bot running on ${port}`));
