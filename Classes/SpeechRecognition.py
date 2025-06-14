import os
import wave
import json
import random
import time
import asyncio
import numpy as np
import concurrent.futures
from pydub import AudioSegment
from pydub.effects import normalize
from pydub.silence import detect_nonsilent
from vosk import Model, KaldiRecognizer, SetLogLevel
from discord.sinks import WaveSink, Sink

# Set Vosk logging level to reduce output
SetLogLevel(-1)

class SpeechRecognizer:
    """
    A speech recognition class that handles processing audio using Vosk.
    This class provides an abstraction over the Vosk speech recognition system.
    """
    
    def __init__(self, model_path=None, keywords=None, temp_dir="temp_audio"):
        """
        Initialize the speech recognizer.
        
        Args:
            model_path (str): Path to the Vosk model directory.
            keywords (list): List of keywords to detect in speech.
            temp_dir (str): Directory to store temporary audio files.
        """
        self.model_path = model_path
        self.model = None
        self.keywords = keywords or []
        self.temp_dir = temp_dir
        
        # Create temp directory if it doesn't exist
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Create a dedicated thread pool executor for STT tasks
        # Adjust max_workers if needed, None uses default (often os.cpu_count() + 4)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=None) 
        print(f"Initialized ThreadPoolExecutor for STT with default workers.")

        # Initialize model
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize the Vosk model."""
        if not self.model_path:
            print("No model path provided, speech recognition disabled")
            return
            
        if not os.path.exists(self.model_path):
            print(f"WARNING: Vosk model not found at {self.model_path}. Speech recognition will not work properly.")
            print("Please download a Vosk model from https://alphacephei.com/vosk/models")
            return
            
        try:
            self.model = Model(self.model_path)
            print(f"Vosk model loaded successfully from {self.model_path}")
        except Exception as e:
            print(f"Error loading Vosk model: {e}")
            self.model = None
    
    async def process_audio_data(self, audio_data, member_name=None):
        """
        Process raw audio data and return recognized text asynchronously.
        
        Args:
            audio_data (bytes): Raw audio data.
            member_name (str): Name of the member who spoke (for logging).
            
        Returns:
            tuple: (detected_text, found_keywords) if speech detected, (None, []) otherwise.
        """
        if not self.model:
            return None, []
            
        # Generate a unique filename for this audio chunk
        unique_id = f"{int(time.time())}_{random.randint(1000, 9999)}"
        temp_file = os.path.join(self.temp_dir, f"{unique_id}.wav")
        
        loop = asyncio.get_running_loop()
        
        try:
            # Write audio data to file (keep this synchronous for quick I/O)
            with wave.open(temp_file, 'wb') as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(48000)
                wf.writeframes(audio_data)
                
            # Process the audio file in a separate thread to avoid blocking
            # Pass necessary arguments to the executor function
            result = await loop.run_in_executor(
                self.executor,  # Use the dedicated executor
                self._process_audio_file, 
                temp_file, 
                member_name
            )
            
            # Clean up
            if os.path.exists(temp_file):
                # Run cleanup in executor too, though usually fast
                await loop.run_in_executor(None, os.remove, temp_file)
                
            return result
            
        except Exception as e:
            print(f"Error processing audio data: {e}")
            # Clean up on error
            if os.path.exists(temp_file):
                 try:
                     # Attempt cleanup in executor
                     await loop.run_in_executor(None, os.remove, temp_file)
                 except Exception as cleanup_e:
                     print(f"Error during cleanup: {cleanup_e}")
            return None, []
    
    def _process_audio_file(self, audio_file_path, member_name=None):
        """
        Process an audio file and return the recognized text.
        
        Args:
            audio_file_path (str): Path to the audio file.
            member_name (str): Name of the member who spoke (for logging).
            
        Returns:
            tuple: (detected_text, found_keywords) if speech detected, (None, []) otherwise.
        """
        try:
            # Load the audio file
            audio = AudioSegment.from_wav(audio_file_path)

            # get only last 10 seconds of audio at most
            if len(audio) > 10000:
                audio = audio[-10000:]
            
            # Normalize the audio to have consistent volume
            audio = normalize(audio)

           
            
            # Check if audio contains actual speech (not just silence)
            # Use more sensitive parameters to detect speech -- ADJUSTING FOR BETTER SEGMENTATION
            non_silent_ranges = detect_nonsilent(
                audio, 
                min_silence_len=350,    # Increased from 250ms - require longer silence to split
                silence_thresh=-32      # Less sensitive threshold (back from -33)
            )
            
            # Skip processing if no speech detected
            if not non_silent_ranges:
                if member_name:
                    print(f"No speech detected in audio from {member_name}, skipping processing")
                return None, []
            
            # Extract only the non-silent parts to process, but add padding to avoid cutting off
            speech_audio = AudioSegment.empty()
            for start_i, end_i in non_silent_ranges:
                # Add a padding of 200ms before each speech segment to catch the beginning
                padded_start = max(0, start_i - 200) # Reduced from 400ms
                # Add a padding of 300ms after each speech segment to avoid cutoff
                padded_end = min(len(audio), end_i + 300) # Reduced from 600ms
                speech_segment = audio[padded_start:padded_end]
                
                # Skip adding very short segments that might be noise
                if len(speech_segment) < 100:  # Skip segments shorter than 100ms
                    continue
                    
                speech_audio += speech_segment
            
            # If we extracted speech, use it instead of the full audio
            if len(speech_audio) > 0:
                audio = speech_audio
            
             # Add 1 second of silence at the beginning and end
            silence = AudioSegment.silent(duration=1000)  # 1000ms = 1 second
            audio = silence + audio + silence
            
            # Check duration and keep only last 10 seconds if longer
            duration_ms = len(audio)
            if duration_ms > 40000:  # 20 seconds in milliseconds
                print(f"Audio too long ({duration_ms/1000:.1f}s), trimming to last 20 seconds")
                audio = audio[-40000:]  # Keep only the last 20 seconds
            
            # Apply audio preprocessing for better recognition
            audio = audio.set_channels(1)  # Convert to mono
            
            # Apply a low-pass filter to remove high-frequency noise that can cause glitches
            audio = audio.low_pass_filter(8000)
            
            # Vosk works best with 16kHz
            audio = audio.set_frame_rate(16000)
            
            # Save as temp mono file
            mono_temp_file = os.path.join(self.temp_dir, f"{os.path.basename(audio_file_path)}_mono.wav")
            audio.export(mono_temp_file, format="wav")
            
            # Process with Vosk
            detected_text = None
            
            with wave.open(mono_temp_file, "rb") as wf:
                # Create a new recognizer for each audio chunk
                rec = KaldiRecognizer(self.model, wf.getframerate())
                
                # Read audio in chunks and process
                # Using larger chunk size for better context
                while True:
                    data = wf.readframes(8000)  # Larger chunks for better context
                    if len(data) == 0:
                        break
                    rec.AcceptWaveform(data)
                
                # Get the final result
                result = json.loads(rec.FinalResult())
                
                # Check all alternatives first
                if "alternatives" in result:
                    for alt in result["alternatives"]:
                        if "text" in alt and alt["text"].strip():
                            alt_text = alt["text"].lower()
                            if any(kw in alt_text for kw in self.keywords):
                                detected_text = alt_text
                                if member_name:
                                    print(f"[{member_name}]: {detected_text} (alternative match)")
                                break
                
                # If no keyword in alternatives, use main result
                if not detected_text and "text" in result and result["text"].strip():
                    detected_text = result["text"].lower()
                    if member_name:
                        print(f"[{member_name}]: {detected_text}")
            
            # Remove the mono temp file after processing
            if os.path.exists(mono_temp_file):
                os.remove(mono_temp_file)
            
            # If we have text, check for keywords
            if detected_text:
                found_keywords = []
                # Check for exact keyword matches
                for kw in self.keywords:
                    if kw.lower() in detected_text:
                        found_keywords.append(kw)
                
                # Enhanced partial matching for specific keywords
                self._check_partial_matches(detected_text, found_keywords)
                
                return detected_text, found_keywords
            
            return None, []
            
        except Exception as e:
            print(f"Error processing audio file: {e}")
            return None, []
            
    def _check_partial_matches(self, text, found_keywords):
        """
        Check for partial matches of keywords.
        This method can be extended for custom partial matching logic.
        
        Args:
            text (str): Detected text.
            found_keywords (list): List to append found keywords to.
        """
        # Example: Special handling for "chapada" with partial matching
        if "chapada" not in found_keywords:
            partial_chapada_matches = {
                "chapada": 1.0,   # Exact match, highest score
                "chapa": 0.8,     # Very close
                "chapá": 0.8,     # Accented variant
                "chapaa": 0.7,    # Common voice recognition error
                "cha": 0.5,       # Partial match
                "chapda": 0.7     # Common voice recognition error
            }
            
            max_score = 0
            for partial, score in partial_chapada_matches.items():
                if partial in text:
                    max_score = max(max_score, score)
            
            # If we have a good enough match, add the keyword
            if max_score >= 0.7:  # Threshold for considering a match
                found_keywords.append("chapada")
                print(f"Partial 'chapada' match detected with score {max_score}")

    def close(self):
        """Shutdown the thread pool executor."""
        print("Shutting down SpeechRecognizer thread pool executor...")
        self.executor.shutdown(wait=True)
        print("SpeechRecognizer thread pool executor shut down.")


class VoiceRecognitionSink(Sink):
    """
    Custom Discord sink for processing voice data.
    This sink collects audio chunks and processes them through a speech recognizer.
    """
    
    def __init__(self, speech_recognizer, event_handler, loop=None, *args, **kwargs):
        """
        Initialize the voice recognition sink.
        
        Args:
            speech_recognizer: The speech recognizer instance to use for processing audio.
            event_handler: Callback function to handle keyword detection events.
            loop: The asyncio event loop to use for scheduling coroutines.
        """
        # Call Sink.__init__, passing encoding explicitly
        super().__init__(*args, **kwargs)
        self.speech_recognizer = speech_recognizer
        self.event_handler = event_handler
        self.loop = loop or asyncio.get_event_loop()  # Store the event loop
        self.audio_data = {}
        self.last_activity = {}
        self.timeout_tasks = {}
        self.processing = set()    # Track which users are currently being processed
        self.last_processed = {}   # Track when each user's audio was last processed
        self.min_process_gap = 0.5 # Increased to 0.5s (was 0.3s) to prevent overlap
        self.silence_count = {}    # Track consecutive silence frames
        self.speaking = {}         # Track if user is speaking
    
    def write(self, data, user):
        """
        Write audio data to the sink.
        This method is called by Discord when new audio data is available.
        
        Args:
            data: The audio data.
            user: The user ID who generated the audio.
        """
        current_time = time.time()
        
        # Skip if we're already processing audio for this user
        if user in self.processing:
            return
            
        # Skip if we just processed audio for this user (prevent overlap)
        if user in self.last_processed and current_time - self.last_processed[user] < self.min_process_gap:
            # Still collect the data, but don't process yet
            if user not in self.audio_data:
                self.audio_data[user] = []
                self.silence_count[user] = 0
                self.speaking[user] = False
            self.audio_data[user].append(data)
            self.last_activity[user] = current_time
            return
            
        # Initialize user data structures if needed
        if user not in self.audio_data:
            self.audio_data[user] = []
            self.silence_count[user] = 0
            self.speaking[user] = False
            
        # Update last activity time for this user
        self.last_activity[user] = current_time
        
        # If user has an existing timeout task, cancel it
        if user in self.timeout_tasks and self.timeout_tasks[user]:
            try:
                self.timeout_tasks[user].cancel()
            except:
                pass
            
        # Add data to main buffer
        self.audio_data[user].append(data)
        
        # Schedule a timeout to process whatever audio we have if user stops talking
        # Use a longer timeout to avoid cutting off speech too early 
        timeout_task = asyncio.run_coroutine_threadsafe(
            self._process_after_silence(user, 0.4),  # 400ms silence timeout (increased from 300ms)
            self.loop
        )
        self.timeout_tasks[user] = timeout_task
    
    async def _process_after_silence(self, user, timeout):
        """
        Process audio after silence is detected.
        
        Args:
            user: The user ID.
            timeout: Time to wait before processing.
        """
        await asyncio.sleep(timeout)
        
        current_time = time.time()
        
        # Only process if we have some audio and no new audio has arrived during the timeout
        if (user in self.audio_data and 
            len(self.audio_data[user]) > 0 and 
            time.time() - self.last_activity[user] >= timeout and
            user not in self.processing):  # Don't process if already processing
            
            # Skip if we just processed audio for this user (prevent overlap)
            if user in self.last_processed and current_time - self.last_processed[user] < self.min_process_gap:
                return
                
            # Make copies of buffers to prevent modification during processing
            audio_chunk = []
            audio_chunk.extend(list(self.audio_data[user].copy()))
            
            # Reset the main buffer and clear the prebuffer immediately after copying
            self.audio_data[user] = []
            
            if len(audio_chunk) >= 15:  # Minimum size
                # Mark this user as being processed
                self.processing.add(user)
                
                # Record when we last processed audio for this user
                self.last_processed[user] = current_time
                
                # Process the audio
                await self.process_audio(user, audio_chunk)
                
        # Clear the timeout task
        self.timeout_tasks[user] = None
    
    async def check_and_clear_old_buffers(self):
        """Clear buffers that haven't been updated in a while to avoid accumulating silence."""
        current_time = time.time()
        for user, last_activity in list(self.last_activity.items()):
            # If no activity for 30 seconds, clear the buffer
            if current_time - last_activity > 30:
                if user in self.audio_data:
                    if len(self.audio_data[user]) > 0:
                        print(f"Clearing stale audio buffer for user {user} (inactive for {current_time - last_activity:.1f}s)")
                    self.audio_data[user] = []
                    
                # If user is marked as processing for too long, clear that too
                if user in self.processing and current_time - last_activity > 60:
                    print(f"Clearing stale processing state for user {user}")
                    self.processing.remove(user)
    
    async def process_audio(self, user, audio_chunks):
        """
        Process audio from a user.
        
        Args:
            user: The user ID.
            audio_chunks: List of audio data chunks.
        """
        try:
            # Join all audio chunks into a single byte array
            audio_data = b''.join(audio_chunks)
            
            # Before processing, ensure there's enough data to work with
            if len(audio_data) < 1000:  # Skip very short audio samples
                return
            
            # Get a better member name placeholder from the cache if available
            if hasattr(self, 'member_cache') and user in self.member_cache:
                member_name = self.member_cache[user]
            else:
                member_name = f"User-{user}"
            
            # Process the audio data with the speech recognizer asynchronously
            detected_text, found_keywords = await self.speech_recognizer.process_audio_data(
                audio_data,
                member_name=member_name
            )
            
            # If we found keywords, notify the event handler
            if found_keywords:
                await self.event_handler(user, detected_text, found_keywords)
                
        except Exception as e:
            print(f"Error processing audio: {e}")
            import traceback
            traceback.print_exc()  # Print detailed error information
        finally:
            # Remove the user from the processing set when done
            if user in self.processing:
                self.processing.remove(user)

    def cleanup(self):
        """Clean up resources associated with the sink."""
        print("Cleaning up VoiceRecognitionSink...")
        # Cancel any pending timeout tasks
        for user, task in list(self.timeout_tasks.items()):
            if task and not task.done():
                try:
                    task.cancel()
                except Exception as e:
                    print(f"Error cancelling task for user {user} during cleanup: {e}")

        # Clear internal state
        self.timeout_tasks.clear()
        self.audio_data.clear()
        self.last_activity.clear()
        self.processing.clear()
        self.last_processed.clear()
        self.silence_count.clear()
        self.speaking.clear()

        # Call the base class cleanup if necessary (Sink.cleanup does nothing by default)
        super().cleanup()


class DiscordVoiceListener:
    """
    A class to handle voice recognition in Discord voice channels.
    """
    
    def __init__(self, bot, speech_recognizer, keyword_action_handler=None):
        """
        Initialize the Discord voice listener.
        
        Args:
            bot: The Discord bot instance.
            speech_recognizer: The speech recognizer to use.
            keyword_action_handler: Callback for handling keyword detections.
        """
        self.bot = bot
        self.speech_recognizer = speech_recognizer
        self.keyword_action_handler = keyword_action_handler
        self.enabled = True
        self.sink_tasks = {}
        self.loop = bot.loop  # Store reference to the bot's event loop
        self.member_cache = {}  # Cache to store member names
    
    def set_enabled(self, enabled):
        """Enable or disable voice recognition."""
        self.enabled = enabled
    
    async def listen_to_voice_channels(self):
        """Main listening loop for voice channels."""
        print("Starting voice channel listening service...")
        print(f"Keyword detection active for: {', '.join(self.speech_recognizer.keywords)}")
        
        while True:
            try:
                # Check if voice recognition is enabled
                if not self.enabled:
                    await asyncio.sleep(5)  # Check less frequently when disabled
                    continue
                    
                # Check all guilds the bot is in
                for guild in self.bot.guilds:
                    # Get the voice client if the bot is in a voice channel in this guild
                    voice_client = guild.voice_client
                    if not voice_client or not voice_client.is_connected():
                        continue
                    
                    # Get users in the voice channel
                    voice_channel = voice_client.channel
                    members = voice_channel.members
                    
                    # Skip if only the bot is in the channel
                    if len(members) <= 1:
                        continue
                    
                    # Log who's in the channel for debugging
                    member_names = [member.name for member in members if member != self.bot.user]
                    
                    # Update member cache with users currently in the channel
                    for member in members:
                        if member != self.bot.user:
                            self.member_cache[member.id] = member.name
                    
                    # Set up sink if not already set up for this voice client
                    if not hasattr(voice_client, 'listening_sink'):
                        # Create keyword detection event handler for this guild and voice channel
                        async def keyword_event_handler(user_id, text, keywords):
                            # Get the member from the user ID
                            member = guild.get_member(user_id)
                            if not member or member == self.bot.user:
                                return
                                
                            # Update cache with member name
                            self.member_cache[user_id] = member.name
                                
                            # Call the action handler if provided
                            if self.keyword_action_handler:
                                await self.keyword_action_handler(guild, voice_channel, member, text, keywords)
                        
                        # Create a custom sink for this voice client with the guild-specific event handler
                        sink = VoiceRecognitionSink(
                            self.speech_recognizer, 
                            keyword_event_handler,
                            loop=self.loop  # Pass the bot's event loop to the sink
                        )
                        
                        # Attach the member_cache to the sink for name resolution
                        sink.member_cache = self.member_cache
                        voice_client.listening_sink = sink
                        
                        # Required callback format for Discord's recording system
                        def recording_callback(sink, user_id, audio_data):
                            # Discord expects this signature: sink, user_id, audio_data
                            # Our sink's write method handles everything
                            pass
                        
                        voice_client.start_recording(sink, recording_callback)
                        print(f"Started recording in {voice_channel.name}")
                        
                        # Set up a task to periodically clear old buffers
                        task = asyncio.create_task(self.periodic_buffer_cleanup(voice_client, sink))
                        self.sink_tasks[voice_client] = task
                
                # Wait before checking again
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"Error in voice listening: {e}")
                await asyncio.sleep(5)  # Wait a bit longer if there's an error
    
    async def periodic_buffer_cleanup(self, voice_client, sink):
        """Periodically clean up old audio buffers."""
        try:
            while voice_client.is_connected():
                await sink.check_and_clear_old_buffers()
                await asyncio.sleep(30)  # Check every 30 seconds
        except Exception as e:
            print(f"Error in buffer cleanup: {e}")
        finally:
            # Remove the task from our tracking
            if voice_client in self.sink_tasks:
                del self.sink_tasks[voice_client] 

    async def start_listening(self, voice_channel):
        """Connect to a voice channel and start listening."""
        guild_id = voice_channel.guild.id
        if not self.enabled:
            print(f"Voice recognition is disabled, not joining {voice_channel.name}.")
            return

        # Check if already connected and listening in this guild
        # if guild_id in self.active_sinks and self.bot.voice_clients:
        #     # Find the specific voice client for this guild
        #     vc = discord.utils.get(self.bot.voice_clients, guild=voice_channel.guild)
        #     if vc and vc.is_connected() and vc.channel == voice_channel:
        #         if not vc.is_listening():
        #             print(f"Already connected to {voice_channel.name}, starting listener...")
        #             try:
        #                 vc.listen(self.active_sinks[guild_id])
        #                 print(f"Restarted listening in {voice_channel.name}.")
        #             except Exception as e:
        #                 print(f"Error restarting listener in {voice_channel.name}: {e}")
        #         else:
        #             # print(f"Already connected and listening in {voice_channel.name}.")
        #             pass # Already listening
        #         return # Exit if already connected and potentially listening
        #     elif vc and vc.is_connected():
        #         # Connected to a different channel in the same guild, stop old listener
        #         print(f"Moving from {vc.channel.name} to {voice_channel.name}. Stopping old listener...")
        #         await self.stop_listening(vc.channel)
        #         # Force disconnect if move doesn't handle it? Usually .move_to handles this
        #         # await vc.disconnect(force=True)
        #         # await asyncio.sleep(1) # Give time for disconnect

        # Attempt to connect or move
        vc = discord.utils.get(self.bot.voice_clients, guild=voice_channel.guild)
        try:
            if vc and vc.is_connected():
                if vc.channel != voice_channel:
                    print(f"Moving to voice channel: {voice_channel.name}")
                    await vc.move_to(voice_channel)
                    # Ensure listener stopped on old channel if move doesn't trigger events cleanly
                    if guild_id in self.active_listeners and self.active_listeners[guild_id].is_listening():
                         print(f"Stopping listener on old channel {vc.channel.name} after move...")
                         self.active_listeners[guild_id].stop()
                         # We might need to clean up the old sink associated with the listener
                         if guild_id in self.active_sinks:
                            self.active_sinks[guild_id].cleanup()
                            del self.active_sinks[guild_id] # Remove old sink reference

                else:
                    print(f"Already connected to {voice_channel.name}.")
                    # If somehow connected but not listening, start it
                    if not vc.is_listening():
                        print(f"Starting listener because not currently listening in {voice_channel.name}.")
                        # Pass
                    else:
                         # Already connected and listening, do nothing else
                         return
            else:
                print(f"Connecting to voice channel: {voice_channel.name}")
                # Ensure cleanup if there was a previous zombie connection
                if guild_id in self.active_listeners:
                     try:
                        self.active_listeners[guild_id].stop()
                     except Exception:
                        pass # Ignore errors stopping non-existent listener
                     del self.active_listeners[guild_id]
                if guild_id in self.active_sinks:
                    self.active_sinks[guild_id].cleanup()
                    del self.active_sinks[guild_id]
                
                vc = await voice_channel.connect()
            
            # --- Always create a NEW sink instance for the connection --- 
            print(f"Creating a new VoiceRecognitionSink for {voice_channel.name}.")
            sink = VoiceRecognitionSink(self.recognizer, self.keyword_callback, voice_channel.guild, voice_channel)
            self.active_sinks[guild_id] = sink 
            # --------------------------------------------------------------

            # Start listening with the new sink
            # Add a small delay before listening? Sometimes helps connection fully establish.
            await asyncio.sleep(0.5) 
            vc.listen(sink, after=lambda e: self.handle_listen_error(e, voice_channel.guild.id))
            self.active_listeners[guild_id] = vc # Store the voice client itself as the listener reference
            print(f"Listening started in {voice_channel.name}")

        except discord.ClientException as e:
            print(f"Error connecting/moving to {voice_channel.name}: {e} - Already connected elsewhere? ")
            # If connection failed, ensure no lingering sink/listener references
            if guild_id in self.active_sinks:
                self.active_sinks[guild_id].cleanup()
                del self.active_sinks[guild_id]
            if guild_id in self.active_listeners:
                 # Attempt to stop listener if it exists
                try:
                    if self.active_listeners[guild_id].is_listening():
                        self.active_listeners[guild_id].stop()
                except Exception as stop_err:
                     print(f"Error stopping listener during connection failure handling: {stop_err}")
                del self.active_listeners[guild_id]
        except asyncio.TimeoutError:
            print(f"Timeout trying to connect/move to {voice_channel.name}.")
            # Cleanup on timeout
            if guild_id in self.active_sinks:
                self.active_sinks[guild_id].cleanup()
                del self.active_sinks[guild_id]
            if guild_id in self.active_listeners:
                try:
                    if self.active_listeners[guild_id].is_listening():
                        self.active_listeners[guild_id].stop()
                except Exception as stop_err:
                     print(f"Error stopping listener during timeout handling: {stop_err}")
                del self.active_listeners[guild_id]
        except Exception as e:
            print(f"An unexpected error occurred in start_listening for {voice_channel.name}: {e}")
            # General cleanup
            if guild_id in self.active_sinks:
                self.active_sinks[guild_id].cleanup()
                del self.active_sinks[guild_id]
            if guild_id in self.active_listeners:
                try:
                    if self.active_listeners[guild_id].is_listening():
                        self.active_listeners[guild_id].stop()
                except Exception as stop_err:
                    print(f"Error stopping listener during general error handling: {stop_err}")
                del self.active_listeners[guild_id] 