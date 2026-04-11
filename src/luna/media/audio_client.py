"""Audio TTS client for Luna RPG v4.

Text-to-Speech using Google Cloud TTS or gTTS fallback.
Supports multiple languages and voice types.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AudioClient:
    """Text-to-Speech client for game narration.
    
    Uses Google Cloud Text-to-Speech API (primary) or gTTS (fallback).
    Supports Italian language with natural-sounding voices.
    """
    
    def __init__(
        self,
        credentials_path: Optional[str] = None,
        language_code: str = "it-IT",
        voice_name: str = "it-IT-Standard-A",
        speaking_rate: float = 1.0,
        pitch: float = 0.0,
    ) -> None:
        """Initialize audio client.
        
        Args:
            credentials_path: Path to Google Cloud credentials JSON
            language_code: Language code (default: it-IT)
            voice_name: Voice name (default: it-IT-Standard-A)
            speaking_rate: Speed (0.25 to 4.0)
            pitch: Voice pitch (-20.0 to 20.0)
        """
        self.credentials_path = credentials_path
        self.language_code = language_code
        self.voice_name = voice_name
        self.speaking_rate = speaking_rate
        self.pitch = pitch
        
        self._client = None
        self._init_client()
    
    def _init_client(self) -> None:
        """Initialize Google Cloud TTS client."""
        try:
            from google.cloud import texttospeech
            
            if self.credentials_path and Path(self.credentials_path).exists():
                self._client = texttospeech.TextToSpeechClient.from_service_account_file(
                    self.credentials_path
                )
            else:
                # Try default credentials
                self._client = texttospeech.TextToSpeechClient()
            
            logger.info("Google Cloud TTS client initialized")
        except ImportError:
            logger.warning("google-cloud-texttospeech not installed, will use gTTS fallback")
            self._client = None
        except Exception as e:
            logger.error(f"Failed to init Google Cloud TTS: {e}")
            self._client = None
    
    def synthesize(
        self,
        text: str,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Synthesize text to speech.
        
        Args:
            text: Text to speak
            output_path: Output file path (optional)
            
        Returns:
            Path to audio file or None if failed
        """
        if not output_path:
            output_path = f"storage/audio/narration_{hash(text) % 10000}.mp3"
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Try Google Cloud TTS first
        if self._client:
            try:
                return self._synthesize_google(text, output_path)
            except Exception as e:
                logger.error(f"Google TTS failed: {e}, trying fallback")
        
        # Fallback to gTTS
        return self._synthesize_gtts(text, output_path)
    
    def _synthesize_google(self, text: str, output_path: str) -> Optional[str]:
        """Use Google Cloud TTS."""
        from google.cloud import texttospeech
        
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        voice = texttospeech.VoiceSelectionParams(
            language_code=self.language_code,
            name=self.voice_name,
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=self.speaking_rate,
            pitch=self.pitch,
        )
        
        response = self._client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        
        with open(output_path, "wb") as out:
            out.write(response.audio_content)
        
        logger.info(f"Audio saved to {output_path}")
        return output_path
    
    def _synthesize_gtts(self, text: str, output_path: str) -> Optional[str]:
        """Use gTTS as fallback (free, no API key needed)."""
        try:
            from gtts import gTTS
            
            # Truncate text if too long (gTTS has limits)
            if len(text) > 500:
                text = text[:497] + "..."
            
            tts = gTTS(text=text, lang="it", slow=False)
            tts.save(output_path)
            
            logger.info(f"Audio (gTTS) saved to {output_path}")
            return output_path
        except ImportError:
            logger.error("gTTS not installed. Install with: pip install gtts")
            return None
        except Exception as e:
            logger.error(f"gTTS failed: {e}")
            return None
    
    def play_audio(self, audio_path: str) -> bool:
        """Play audio file using pygame.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            True if played successfully
        """
        try:
            import pygame
            
            pygame.mixer.init()
            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.play()
            
            # Wait for playback to finish
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            
            return True
        except ImportError:
            logger.warning("pygame not installed, cannot play audio")
            return False
        except Exception as e:
            logger.error(f"Failed to play audio: {e}")
            return False
