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
    secret: 'dev_secret_odisha_debug',
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

// ================= UPLOAD WITH FULL LOGGING =================
app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.session.loggedIn) return res.status(403).json({ success: false, message: "Unauthorized" });
    if (!req.file) return res.status(400).json({ success: false, message: "No file" });

    const filePath = req.file.path;
    const originalName = req.file.originalname;
    const fileSize = req.file.size;

    console.log(`\n=== NEW UPLOAD STARTED ===`);
    console.log(`File: ${originalName} | Size: ${fileSize} bytes`);

    try {
        // 1. Get Upload Server
        console.log(`Step 1: Fetching Upload Server for Key: ${apiKey.substring(0, 5)}...`);
        const serverRes = await axios.get(`https://devuploads.com/api/upload/server?key=${apiKey}`);
        
        // LOG RAW RESPONSE
        console.log("API RAW RESPONSE:", JSON.stringify(serverRes.data, null, 2));

        if (!serverRes.data || !serverRes.data.result) {
            throw new Error("Failed to get server URL from API");
        }
        
        const uploadUrl = serverRes.data.result;
        console.log(`Step 2: Got URL: ${uploadUrl}`);

        // 2. Extract sess_id
        let sessId = "";
        if (uploadUrl.includes('sess_id=')) {
            sessId = uploadUrl.split('sess_id=')[1].split('&')[0];
            console.log(`Session ID Found: ${sessId}`);
        } else {
            console.warn("⚠️ WARNING: sess_id MISSING in URL! This might cause 500 Error.");
        }

        // 3. Prepare Form
        const form = new FormData();
        form.append('key', apiKey);
        if (sessId) form.append('sess_id', sessId);
        form.append('upload_type', 'file');
        
        // File append with known length (Important for CGI servers)
        form.append('file', fs.createReadStream(filePath), { 
            filename: originalName,
            knownLength: fileSize 
        });

        const requestHeaders = {
            ...form.getHeaders(),
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        };

        console.log("Step 3: Sending file to DevUploads...");
        // console.log("Request Headers:", JSON.stringify(requestHeaders, null, 2)); // Uncomment for deep debug

        // 4. Send File
        const uploadRes = await axios.post(uploadUrl, form, {
            headers: requestHeaders,
            maxContentLength: Infinity,
            maxBodyLength: Infinity
        });

        // Cleanup
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);

        console.log("Step 4: Upload Response Status:", uploadRes.status);
        console.log("Upload Response Data:", JSON.stringify(uploadRes.data));

        if (uploadRes.data && uploadRes.status === 200) {
            // Check if DevUploads returned an error inside 200 OK
            if (uploadRes.data.filecode || (Array.isArray(uploadRes.data) && uploadRes.data[0].file_code)) {
                 const code = uploadRes.data.filecode || uploadRes.data[0].file_code;
                 const link = `https://devuploads.com/${code}`;
                 res.json({ success: true, link: link });
            } else if (uploadRes.data.result && uploadRes.data.result[0]) {
                 const code = uploadRes.data.result[0].filecode;
                 const link = `https://devuploads.com/${code}`;
                 res.json({ success: true, link: link });
            } else {
                 console.error("Unknown Response Format:", uploadRes.data);
                 res.json({ success: false, message: "Upload success but link missing. Check logs." });
            }
        } else {
            res.json({ success: false, message: "Upload Failed" });
        }

    } catch (err) {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        
        console.error("\n=== ERROR OCCURRED ===");
        if (err.response) {
            // Server responded with a status code (like 500)
            console.error(`Status: ${err.response.status}`);
            console.error(`Headers:`, JSON.stringify(err.response.headers));
            console.error(`Data (HTML/Text):`, err.response.data); // Ye dikhayega asli server error
            
            res.status(500).json({ 
                success: false, 
                message: `Server Error ${err.response.status}. Check Logs for HTML details.` 
            });
        } else {
            // Network or Code error
            console.error("Error Message:", err.message);
            res.status(500).json({ success: false, message: err.message });
        }
    }
});

app.listen(port, () => console.log(`Debug Bot running on ${port}`));
