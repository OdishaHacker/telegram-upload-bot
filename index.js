const express = require('express');
const multer = require('multer');
const axios = require('axios');
const FormData = require('form-data');
const session = require('express-session');
const fs = require('fs');
const path = require('path');

const app = express();
// Multer setup
const upload = multer({ dest: 'uploads/' });

// ================= ENV & CONFIG =================
const apiKey = process.env.DEVUPLOADS_API_KEY; 
const adminUser = process.env.ADMIN_USER || "Admin";
const adminPass = process.env.ADMIN_PASS || "12345";
const port = process.env.PORT || 5000;

// Session Middleware
app.use(session({
    secret: 'dev_secret_odisha_hacker',
    resave: false,
    saveUninitialized: true
}));

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(express.static(path.join(__dirname, 'public')));

// ================= AUTH ROUTES =================
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

// ================= UPLOAD ROUTE (FIXED) =================
app.post('/upload', upload.single('file'), async (req, res) => {
    // 1. Basic Checks
    if (!req.session.loggedIn) return res.status(403).json({ success: false, message: "Unauthorized" });
    if (!req.file) return res.status(400).json({ success: false, message: "No file selected" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;
    const mimeType = req.file.mimetype;

    console.log(`Starting upload for: ${originalName} (${req.file.size} bytes)`);

    try {
        // 2. Get Upload Server (With Timeout & Headers)
        const serverRes = await axios.get(`https://devuploads.com/api/upload/server?key=${apiKey}`, {
            timeout: 10000,
            headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' }
        });

        if (!serverRes.data || !serverRes.data.result) {
            throw new Error(`Failed to get upload server. API Response: ${JSON.stringify(serverRes.data)}`);
        }
        
        const uploadUrl = serverRes.data.result;
        console.log(`Got Upload URL: ${uploadUrl}`);

        // 3. Prepare Form Data (Browser Simulation)
        const form = new FormData();
        form.append('key', apiKey);
        form.append('file', fs.createReadStream(filePath), {
            filename: originalName,
            contentType: mimeType,
        });

        // 4. Send File (Pretending to be a Browser)
        const uploadRes = await axios.post(uploadUrl, form, {
            headers: { 
                ...form.getHeaders(),
                // Ye header zaroori hai taaki DevUploads block na kare
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            },
            maxContentLength: Infinity,
            maxBodyLength: Infinity,
            timeout: 0 // No timeout for upload
        });

        // Cleanup local file immediately
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);

        // 5. Check Result
        if (uploadRes.data && uploadRes.data.status === 200) {
            const fileCode = uploadRes.data.result[0].filecode;
            const finalLink = `https://devuploads.com/${fileCode}`;
            console.log(`Upload Success: ${finalLink}`);
            res.json({ success: true, link: finalLink });
        } else {
            console.error("API Rejected Upload:", uploadRes.data);
            const msg = uploadRes.data.msg || "Unknown API Error";
            res.json({ success: false, message: `DevUploads Error: ${msg}` });
        }

    } catch (err) {
        // Cleanup on error
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        
        let errorDetails = err.message;
        if (err.response && err.response.data) {
            errorDetails = JSON.stringify(err.response.data);
        }

        console.error("CRITICAL UPLOAD ERROR:", errorDetails);
        res.status(500).json({ success: false, message: errorDetails });
    }
});

app.listen(port, () => {
    console.log(`Server running on port ${port}`);
});
