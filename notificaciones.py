"""
Notification Helper for ErgoVision
Handles desktop notifications and system sounds
"""

import time
import threading
import platform
import os
from plyer import notification


def play_system_sound(sound_type='default'):
    """
    Play system sounds (cross-platform)
    
    Args:
        sound_type: 'default', 'alert', 'warning', 'success'
    """
    system = platform.system()
    
    try:
        if system == 'Darwin':  # macOS
            sounds = {
                'default': '/System/Library/Sounds/Ping.aiff',
                'alert': '/System/Library/Sounds/Basso.aiff',
                'warning': '/System/Library/Sounds/Sosumi.aiff',
                'success': '/System/Library/Sounds/Glass.aiff',
            }
            sound_file = sounds.get(sound_type, sounds['default'])
            os.system(f'afplay {sound_file}')
            
        elif system == 'Linux':
            sounds = {
                'default': '/usr/share/sounds/freedesktop/stereo/message.oga',
                'alert': '/usr/share/sounds/freedesktop/stereo/dialog-warning.oga',
                'warning': '/usr/share/sounds/freedesktop/stereo/suspend-error.oga',
                'success': '/usr/share/sounds/freedesktop/stereo/complete.oga',
            }
            sound_file = sounds.get(sound_type, sounds['default'])
            if os.path.exists(sound_file):
                os.system(f'paplay {sound_file}')
            else:
                # Fallback to beep
                os.system('paplay /usr/share/sounds/freedesktop/stereo/bell.oga 2>/dev/null || beep')
                
        elif system == 'Windows':
            import winsound
            sound_map = {
                'default': winsound.MB_OK,
                'alert': winsound.MB_ICONEXCLAMATION,
                'warning': winsound.MB_ICONHAND,
                'success': winsound.MB_ICONASTERISK,
            }
            sound = sound_map.get(sound_type, winsound.MB_OK)
            winsound.MessageBeep(sound)
            
    except Exception as e:
        print(f"⚠️ Could not play system sound: {e}")


class NotificationManager:
    """
    Manages desktop notifications with cooldown periods and system sounds
    """
    
    def __init__(self, cooldown_seconds=300):
        """
        Initialize the notification manager
        
        Args:
            cooldown_seconds: Minimum time between notifications of the same type
        """
        self.last_notifications = {}
        self.cooldown = cooldown_seconds
    
    def can_notify(self, notification_type):
        """Check if enough time has passed since last notification of this type"""
        last_time = self.last_notifications.get(notification_type, 0)
        return time.time() - last_time > self.cooldown
    
    def send(self, notification_type, title, message, sound_type='default', play_sound=True):
        """
        Send a desktop notification with optional system sound
        
        Args:
            notification_type: Unique identifier for this type of notification
            title: Notification title
            message: Notification message
            sound_type: Type of system sound ('default', 'alert', 'warning', 'success')
            play_sound: Whether to play sound
            
        Returns:
            True if notification was sent, False if cooldown not elapsed
        """
        if self.can_notify(notification_type):
            try:
                # Send desktop notification
                notification.notify(
                    title=title,
                    message=message,
                    app_name='ErgoVision Wellness',
                    timeout=10  # seconds
                )
                
                # Play system sound in separate thread to avoid blocking
                if play_sound:
                    threading.Thread(
                        target=play_system_sound, 
                        args=(sound_type,), 
                        daemon=True
                    ).start()
                
                # Update last notification time
                self.last_notifications[notification_type] = time.time()
                return True
                
            except Exception as e:
                print(f"❌ Notification error: {e}")
                return False
        return False
    
    def reset_type(self, notification_type):
        """Reset cooldown for a specific notification type"""
        if notification_type in self.last_notifications:
            del self.last_notifications[notification_type]
    
    def reset_all(self):
        """Reset all notification cooldowns"""
        self.last_notifications.clear()


# Predefined notification messages with sound types
NOTIFICATION_MESSAGES = {
    'posture_bad_side': {
        'title': '⚠️ Alerta de Postura (Lateral)',
        'message': 'Has mantenido una mala postura. Endereza tu cuello y espalda.',
        'sound': 'warning'
    },
    'posture_bad_front': {
        'title': '⚠️ Alerta de Postura (Frontal)',
        'message': 'Has mantenido una mala postura. Endereza tu cuello y espalda.',
        'sound': 'warning'
    },
    'lighting_low_side': {
        'title': '💡 Alerta de Iluminación (Lateral)',
        'message': 'La iluminación es insuficiente. Aumenta la luz ambiente.',
        'sound': 'alert'
    },
    'lighting_low_front': {
        'title': '💡 Alerta de Iluminación (Frontal)',
        'message': 'La iluminación es insuficiente. Aumenta la luz ambiente.',
        'sound': 'alert'
    },
    'hydration_reminder': {
        'title': '💧 Recordatorio de Hidratación',
        'message': 'Es hora de tomar agua. Mantente hidratado.',
        'sound': 'default'
    },
    'sitting_too_long': {
        'title': '🚶 Hora de Moverse',
        'message': 'Has estado sentado mucho tiempo. Toma un descanso.',
        'sound': 'default'
    },
}


def get_notification_message(notification_type, **kwargs):
    """
    Get notification message with optional formatting
    
    Args:
        notification_type: Type of notification
        **kwargs: Additional formatting parameters
        
    Returns:
        Dictionary with 'title', 'message', and 'sound'
    """
    if notification_type in NOTIFICATION_MESSAGES:
        msg = NOTIFICATION_MESSAGES[notification_type].copy()
        
        # Format message with kwargs if provided
        if kwargs:
            msg['message'] = msg['message'].format(**kwargs)
        
        return msg
    
    return {
        'title': 'ErgoVision Alert',
        'message': 'Please check your wellness dashboard',
        'sound': 'default'
    }