import Live
from .MIDI_Gadget import MIDI_Gadget


def create_instance(c_instance):
    """ Creates and returns the APC20 script """
    return MIDI_Gadget(c_instance)

# local variables:
# tab-width: 4
