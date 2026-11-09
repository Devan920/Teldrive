import httpx

BOT_TOKEN = "9106932386:AAGKiG8bPPYVYdpo7OVDKcKC6qNXGK3SynE"
CHAT_ID = "1563056827"

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
data = {
    "chat_id": CHAT_ID,
    "text": "ഹലോ! ടെലിഗ്രാം ക്ലൗഡ് സ്റ്റോറേജ് കണക്ഷൻ സക്സസ്ഫുൾ ആയി സെറ്റ് ആയിട്ടുണ്ട്."
}

res = httpx.post(url, data=data).json()

if res.get("ok"):
    print("സെറ്റാണ്! ടെലിഗ്രാമിൽ മെസ്സേജ് വന്നിട്ടുണ്ട്.")
else:
    print("എറർ വന്നു:", res.get("description"))