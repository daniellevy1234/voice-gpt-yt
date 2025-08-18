# -- coding: utf-8 --
# recovery code for twillo 56ZGZ6L8P7Q59M7LVGA2BKQ5
from flask import Flask, request, redirect, Response, send_from_directory
from twilio.twiml.voice_response import VoiceResponse, Gather
from openai import OpenAI
import os
import requests
from bs4 import BeautifulSoup
import yt_dlp

# Initialize the Flask application
app = Flask(__name__)

# Initialize the OpenAI client using the environment variable
# The API key is automatically provided in the environment.
client = OpenAI()

# Dictionaries to store session data.
# Note: For a production environment, it is highly recommended to use a database
# like Redis or Firestore to manage sessions across multiple processes.
sessions = {}
recent_songs = {}
podcast_cache = {}

# Dictionary of live stream URLs, mapped to channel digits.
live_streams = {
    "1": {"name": "Channel 12", "url": "https://keshet-livestream.cdn.mk12.streamweb.co.il/live/keshet.stream/playlist.m3u8"},
    "2": {"name": "Channel 11", "url": "https://kan11live.makan.org.il/kan11/live/playlist.m3u8"},
    "3": {"name": "Channel 13", "url": "https://13tv-live.cdnwiz.com/live/13tv/13tv/playlist.m3u8"},
    "4": {"name": "Channel 14", "url": "https://kan14live.makan.org.il/kan14/live/playlist.m3u8"},
    "5": {"name": "i24", "url": "https://i24hls-i.akamaihd.net/hls/live/2037040/i24newsenglish/index.m3u8"}
}

# Define the base URL for the application.
# This should be updated for your specific deployment.
BASE_URL = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "127.0.0.1:5000")

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    """
    Handles the initial call and presents the main menu.
    """
    resp = VoiceResponse()

    # The Twilio Gather verb waits for user input.
    gather = Gather(num_digits=1, action="/menu", method="POST", timeout=5)
    prompt = (
        "Welcome to the system."
        "To talk with GPT, press 1."
        "To request a song, press 2."
        "For live broadcasts, press 3."
        "For a news bulletin, press 4."
        "For the Yinon and Ben show, press 5."
        "To hear the latest songs you played, press 6."
        "To exit, press 9."
    )
    gather.say(prompt, language="en-US", voice="Polly.Joanna")
    resp.append(gather)

    # Redirect to the menu on a timeout to keep the loop going.
    resp.redirect("/voice")

    return Response(str(resp), mimetype='text/xml')

@app.route("/menu", methods=['POST'])
def menu():
    """
    Routes the call based on the user's digit input from the main menu.
    """
    choice = request.form.get("Digits")
    route_map = {
        "1": "/gpt-prompt",
        "2": "/song-prompt",
        "3": "/live-prompt",
        "4": "/ynet-news",
        "5": "/yinon-podcast",
        "6": "/recent-songs",
    }
    resp = VoiceResponse()

    if choice in route_map:
        return redirect(route_map[choice])
    elif choice == "9":
        resp.say("Thank you for calling! Goodbye.", language="en-US", voice="Polly.Joanna")
        resp.hangup()
        return str(resp)
    else:
        resp.say("Invalid choice, please try again.", language="en-US", voice="Polly.Joanna")
        resp.redirect("/voice")
        return str(resp)

@app.route("/gpt-prompt", methods=['GET', 'POST'])
def gpt_prompt():
    """
    Initiates the GPT conversation and provides instructions.
    """
    resp = VoiceResponse()
    prompt = (
        "You have entered conversation mode with GPT. "
        "To return to the main menu at any time, say 'Return to menu'. "
        "What is your first question?"
    )
    # The Gather verb with input="speech" enables voice recognition.
    gather = Gather(input="speech", action="/handle-gpt-response", timeout=7, language="en-US")
    gather.say(prompt, language="en-US", voice="Polly.Joanna")
    resp.append(gather)

    return str(resp)

@app.route("/handle-gpt-response", methods=['POST'])
def handle_gpt_response():
    """
    Manages the conversation with GPT, handling user speech and providing responses.
    """
    resp = VoiceResponse()
    call_sid = request.form.get("CallSid")
    speech_result = request.form.get("SpeechResult")

    # Handle the "main menu" command from the user.
    if speech_result and ("go back to main menu" in speech_result.lower() or "main menu" in speech_result.lower()):
        resp.say("Sure, returning to the main menu.", language="en-US", voice="Polly.Joanna")
        resp.redirect("/voice")
        return str(resp)

    # Handle cases where no speech was detected.
    if not speech_result:
        resp.say("I didn't hear you. Returning to the main menu.", language="en-US", voice="Polly.Joanna")
        resp.redirect("/voice")
        return str(resp)

    # Set up conversation memory for a new call ID.
    if call_sid not in sessions:
        sessions[call_sid] = [
            {"role": "system", "content": "Answer in English, briefly and clearly and Only answer in plain text."}
        ]

    # Save the user's input to the session history.
    sessions[call_sid].append({"role": "user", "content": speech_result})

    try:
        # Call the OpenAI API to get a response.
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=sessions[call_sid]
        )
        answer = response.choices[0].message.content

        # Save the GPT answer to the session history.
        sessions[call_sid].append({"role": "assistant", "content": answer})

        # Trim conversation memory to prevent it from getting too long.
        if len(sessions[call_sid]) > 20:
            sessions[call_sid] = sessions[call_sid][-20:]

        # Say the answer back to the caller.
        resp.say(answer, language="en-US", voice="Polly.Joanna")

        # Keep the conversation loop going.
        gather = Gather(
            input="speech",
            action="/handle-gpt-response",
            timeout=7,
            language="en-US"
        )
        gather.say("You can continue speaking.", language="en-US", voice="Polly.Joanna")
        resp.append(gather)

    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        resp.say("Sorry, there was an error receiving the answer from GPT. Returning to the main menu.", language="en-US", voice="Polly.Joanna")
        resp.redirect("/voice")

    return str(resp)


@app.route("/song-prompt", methods=['GET', 'POST'])
def song_prompt():
    """
    Asks the user to say the name of a song they want to play.
    """
    resp = VoiceResponse()
    gather = Gather(input="speech", action="/play-song", timeout=5, language="en-US")
    gather.say("Please say the name of the song you are looking for.", language="en-US", voice="Polly.Joanna")
    resp.append(gather)
    resp.redirect("/voice")
    return str(resp)

@app.route("/play-song", methods=['POST'])
def play_song():
    """
    Tries to find and play a song from YouTube.
    """
    resp = VoiceResponse()
    speech = request.form.get("SpeechResult")
    call_sid = request.form.get("CallSid")

    if speech:
        # Search YouTube for the song.
        try:
            # We'll use yt-dlp to find the stream URL.
            # We configure it to search for the best audio stream and a single result.
            ydl_opts = {
                'format': 'bestaudio/best',
                'default_search': 'ytsearch1',
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(speech, download=False)
                # Check if a video was found.
                if info_dict and 'entries' in info_dict and info_dict['entries']:
                    video_info = info_dict['entries'][0]
                    title = video_info.get('title', 'a song')
                    stream_url = video_info['url']
                    
                    resp.say(f"Searching on YouTube. I found, {title}. Playing it now.", language="en-US", voice="Polly.Joanna")
                    # Add to recent songs for playback later.
                    recent_songs.setdefault(call_sid, []).append(title)
                    resp.play(stream_url)
                else:
                    resp.say("I couldn't find that song on YouTube. Please try another one.", language="en-US", voice="Polly.Joanna")
        except Exception as e:
            print(f"Error searching or playing from YouTube: {e}")
            resp.say("Sorry, an error occurred while searching YouTube. Returning to the main menu.", language="en-US", voice="Polly.Joanna")
    else:
        resp.say("I didn't hear a song name. Please try again.", language="en-US", voice="Polly.Joanna")

    resp.redirect("/voice")
    return str(resp)

@app.route("/recent-songs", methods=['GET', 'POST'])
def recent_songs_playback():
    """
    Plays back the last requested songs from the user's session history.
    """
    resp = VoiceResponse()
    call_sid = request.form.get("CallSid")
    songs_to_play = recent_songs.get(call_sid, [])
    
    if songs_to_play:
        resp.say("Playing the last songs you requested.", language="en-US", voice="Polly.Joanna")
        # Play songs in reverse chronological order.
        for song_query in reversed(songs_to_play):
            # Re-fetch the YouTube URL since we don't store the file.
            try:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'default_search': 'ytsearch1',
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(song_query, download=False)
                    if info_dict and 'entries' in info_dict and info_dict['entries']:
                        video_info = info_dict['entries'][0]
                        stream_url = video_info['url']
                        resp.say(f"Next up is: {song_query}", language="en-US", voice="Polly.Joanna")
                        resp.play(stream_url)
                    else:
                        resp.say(f"I couldn't find {song_query} again.", language="en-US", voice="Polly.Joanna")
            except Exception as e:
                print(f"Error re-fetching YouTube song: {e}")
                resp.say(f"I'm sorry, I couldn't re-find {song_query}.", language="en-US", voice="Polly.Joanna")
    else:
        resp.say("No songs were found in your history.", language="en-US", voice="Polly.Joanna")
    
    resp.redirect("/voice")
    return str(resp)

@app.route("/live-prompt", methods=['GET', 'POST'])
def live_prompt():
    """
    Presents the user with a menu of live channels to choose from.
    """
    resp = VoiceResponse()
    gather = Gather(num_digits=1, action="/play-live", method="POST")
    prompt = (
        "For Channel 12, press 1. "
        "For Channel 11, press 2. "
        "For Channel 13, press 3. "
        "For Channel 14, press 4. "
        "For i24, press 5."
    )
    gather.say(prompt, language="en-US", voice="Polly.Joanna")
    resp.append(gather)
    resp.redirect("/voice")
    return str(resp)

@app.route("/play-live", methods=['POST'])
def play_live():
    """
    Connects to the live stream based on the user's digit input.
    """
    resp = VoiceResponse()
    digit = request.form.get("Digits")
    
    if digit in live_streams:
        channel = live_streams[digit]
        resp.say(f"Connecting to {channel['name']}.", language="en-US", voice="Polly.Joanna")
        resp.play(channel['url'])
    else:
        resp.say("Invalid channel.", language="en-US", voice="Polly.Joanna")
    
    resp.redirect("/voice")
    return str(resp)

@app.route("/ynet-news", methods=['GET', 'POST'])
def ynet_news():
    """
    Scrapes Ynet for top headlines and reads them back to the user.
    """
    resp = VoiceResponse()
    resp.say("Checking the top headlines from Ynet.", language="en-US", voice="Polly.Joanna")
    
    try:
        r = requests.get("https://www.ynet.co.il/news", timeout=5)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        headlines = [item.get_text(strip=True) for item in soup.select(".slotTitle a")[:5]]
        if headlines:
            news_string = ". ".join(headlines)
            resp.say(news_string, language="en-US", voice="Polly.Joanna")
        else:
            resp.say("I couldn't find any news headlines.", language="en-US", voice="Polly.Joanna")
            
    except Exception as e:
        print(f"Error fetching Ynet news: {e}")
        resp.say("There was an error retrieving the news.", language="en-US", voice="Polly.Joanna")

    resp.redirect("/voice")
    return str(resp)

@app.route("/yinon-podcast", methods=['GET', 'POST'])
def yinon_podcast():
    """
    Plays the most recent Yinon and Ben podcast episode by scraping the 103FM website.
    """
    resp = VoiceResponse()
    
    try:
        # Scrape 103FM to find the latest podcast URL
        if "yinon_url" not in podcast_cache:
            resp.say("Fetching the latest podcast episode.", language="en-US", voice="Polly.Joanna")
            podcast_url = find_latest_podcast_url()
            if podcast_url:
                podcast_cache["yinon_url"] = podcast_url
            else:
                raise Exception("Could not find podcast URL")
        
        resp.say("Playing the latest episode of The show of Yinon Magal and Ben Caspit.", language="en-US", voice="Polly.Joanna")
        resp.play(podcast_cache["yinon_url"])

    except Exception as e:
        print(f"Error fetching podcast: {e}")
        resp.say("I'm sorry, I couldn't find the podcast at this time. Returning to the main menu.", language="en-US", voice="Polly.Joanna")
    
    resp.redirect("/voice")
    return str(resp)

def find_latest_podcast_url():
    """
    Helper function to scrape 103FM's website for the latest podcast URL.
    Returns the URL string or None if not found.
    """
    try:
        r = requests.get("https://103fm.maariv.co.il/", timeout=5)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        
        # Look for the "Yinon and Ben" podcast section. This selector might need to be adjusted
        # if the website's HTML changes.
        podcast_link = soup.select_one('a[href*="/Yinon-Magal"]')
        if podcast_link and podcast_link.has_attr('href'):
            # The full URL is sometimes in a nested link or a script,
            # this is a more direct way to find the latest MP3 link.
            # We'll assume the direct MP3 link is in the main page's HTML,
            # and search for it from there. A more robust solution might require a separate request
            # to the specific podcast page.
            latest_mp3_link = soup.select_one('a[href$=".mp3"]')
            if latest_mp3_link and latest_mp3_link.has_attr('href'):
                return latest_mp3_link['href']
    except Exception as e:
        print(f"Error scraping podcast page: {e}")
        return None

if __name__ == "__main__":
    app.run(debug=True)
