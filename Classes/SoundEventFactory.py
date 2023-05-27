from Classes.SoundEvent import SoundEvent

class SoundEventFactory:
    @staticmethod
    def create_sound_event(user, event, sound):
        return SoundEvent(user, event, sound)
