const express = require('express');
const multer = require('multer');
const TelegramBot = require('node-telegram-bot-api');
const fs = require('fs');

const app = express();
const upload = multer({ dest: 'uploads/' });

// Token aur Channel ID hum Coolify se lenge (Code mein nahi likhenge)
const token = process.env.BOT_TOKEN;
const channelId = process.env.CHANNEL_ID;
const port = process.env.PORT || 3000;

// Bot setup
const bot = new TelegramBot(token, { polling: false });

app.use(express.static('public'));

app.post('/upload', upload.single('file'), async (req, res) => {
    if (!req.file) {
        return res.status(400).send('No file uploaded.');
    }

    const filePath = req.file.path;
    const originalName = req.file.originalname;

    try {
        await bot.sendDocument(channelId, fs.createReadStream(filePath), {}, {
            filename: originalName,
            contentType: req.file.mimetype
        });

        // Kaam hone ke baad file delete karein
        fs.unlinkSync(filePath);
        res.json({ success: true, message: 'File sent to Telegram!' });

    } catch (error) {
        console.error(error);
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
        res.status(500).json({ success: false, error: error.message });
    }
});

app.listen(port, () => {
    console.log(`Server running on port ${port}`);
});
