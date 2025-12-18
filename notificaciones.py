import time
import threading
import platform
import os
from plyer import notification


def play_system_sound(sound_type='default'):
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
        print(f"⚠️ No se pudo reproducir el sonido del sistema: {e}")


class NotificationManager:

    def __init__(self, cooldown_seconds=300):
        self.last_notifications = {}
        self.cooldown = cooldown_seconds
    
    def can_notify(self, notification_type):
        """Verifica si ha pasado el tiempo de cooldown para este tipo de notificación"""
        last_time = self.last_notifications.get(notification_type, 0)
        return time.time() - last_time > self.cooldown
    
    def send(self, notification_type, title, message, sound_type='default', play_sound=True):
        """Envía una notificación de escritorio con sonido opcional"""
        if self.can_notify(notification_type):
            try:
                # Enviar notificación de escritorio
                notification.notify(
                    title=title,
                    message=message,
                    app_name='ErgoVision Wellness',
                    timeout=10  # seconds
                )
                
                # Reproducir sonido del sistema en un hilo separado para evitar bloqueo
                if play_sound:
                    threading.Thread(
                        target=play_system_sound, 
                        args=(sound_type,), 
                        daemon=True
                    ).start()
                
                # Actualizar tiempo de la última notificación
                self.last_notifications[notification_type] = time.time()
                return True
                
            except Exception as e:
                print(f"❌ Error en la notificación: {e}")
                return False
        return False
    
    def reset_type(self, notification_type):
        """Restablecer el cooldown para un tipo específico de notificación"""
        if notification_type in self.last_notifications:
            del self.last_notifications[notification_type]
    
    def reset_all(self):
        """Restablecer todos los cooldowns de notificaciones"""
        self.last_notifications.clear()


# Notificaciones predefinidas
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
    if notification_type in NOTIFICATION_MESSAGES:
        msg = NOTIFICATION_MESSAGES[notification_type].copy()
        
        # Formatear mensaje con kwargs si se proporcionan
        if kwargs:
            msg['message'] = msg['message'].format(**kwargs)
        
        return msg
    
    return {
        'title': 'ErgoVision Alert',
        'message': 'Porfavor, atiende a la notificación.',
        'sound': 'default'
    }