#Matthew Baum and Dhruv Mittal

import pygame
from pygame.locals import *
import os

import time
import RPi.GPIO as GPIO
import threading

#init
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

#config
import mido
from mido import Message

outport = mido.open_output('f_midi')
inport = mido.open_input('f_midi')

#ROTARY ENCODER SETUP
import evdev
import select
devices = [evdev.InputDevice(fn) for fn in evdev.list_devices()]
rotary1fd = 0 
rotary2fd = 0
for dev in devices:
  if dev.name == "rotary@e": #val 1, event 5
    rotary1fd = dev.fd
  elif dev.name == "rotary@a": #value 2, event 4
    rotary2fd = dev.fd
devices = {dev.fd: dev for dev in devices}

#fader 1 config
GPIO.setup(25, GPIO.OUT)
pwm25 = GPIO.PWM(25, 150)
AI1 = 23
AI2 = 24
GPIO.setup(AI1, GPIO.OUT) #push down, pin AI1
GPIO.setup(AI2, GPIO.OUT) #push up, pin AI2

#fader 2 config
GPIO.setup(13, GPIO.OUT)
pwm13 = GPIO.PWM(13, 150)
BI1 = 26
BI2 = 19
GPIO.setup(BI1, GPIO.OUT) #push down, pin AI1
GPIO.setup(BI2, GPIO.OUT) #push up, pin AI2

#ADC SETUP
import board
import busio
i2c = busio.I2C(board.SCL, board.SDA)
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
ads = ADS.ADS1115(i2c, address=0x49)
chan1 = AnalogIn(ads, ADS.P0)
chan2 = AnalogIn(ads, ADS.P1)
max_adc = 26340
adc_lock = threading.Lock()
# check fader's volume level from board - update accordingly
def get_fader_1():
	with adc_lock:
		read = chan1.value/max_adc
	norm = max(0.0,read)
	#log_curve = norm**0.9
	volume_new = round(norm*127)
	volume_new = min(127,volume_new)
	return volume_new

# check fader's volume level from board - update accordingly
def get_fader_2():
	with adc_lock:
		read = chan2.value/max_adc
	norm = max(0.0,read)
	#log_curve = norm**0.9
	volume_new = round(norm*127)
	volume_new = min(127,volume_new)
	#print(volume_new)
	return volume_new

def midi_to_volume(vol):
	val = vol/127
	val = val ** (1/0.9)
	val = val * max_adc
	return val

def setNextButton():
    global next_pressed
    next_pressed = False
    

#bank - 8 tracks, offset of 3. 3*7 = 21 which is the highest offset
pan_offset=0
button_offset = 0
fader_offset = 0
GPIO.setup(22, GPIO.IN, pull_up_down=GPIO.PUD_UP)
next_pressed = False	
def update_bank(channel):
	global button_offset, fader_offset, pan_offset, receiving
	receiving = True
	button_offset = (button_offset+1)%7
	fader_offset = (fader_offset+1)%7
	pan_offset = (pan_offset+1)%7
	#update states
	#t1 = threading.Thread(target=receive_fader_1, args=(midi_dict[(0,fader_offset)],0.5,))
	#t1.start()
	#receive_fader_2(midi_dict[(0,fader_offset+1)],0.5)
	#t1.join()
	global next_pressed
	next_pressed = True
	threading.Timer(0.35, lambda: setNextButton()).start()
	#print ("offset = " + str(button_offset))
GPIO.add_event_detect(22, GPIO.RISING, callback=update_bank, bouncetime=400)

#Button States
#mute1,solo1,arm1,mute2,solo2,arm2,play,stop,record
button_dict = {21:(1,0), 20:(1,8), 16:(1,16), 12:(1,1), 8:(1,9), 7:(1,17)}
playback_dict = {27:(1,24), 17:(1,25), 4:(1,26)}

# midi for faders and pan for just 1 track for now
midi_dict = {}
#faders and pan
for i in range(8):
	midi_dict[(0,i)] = 108
	midi_dict[(0,i+8)] = 64

#track control
for i in range(0,8):
	midi_dict[(1,i)] = 127
for i in range(8,24):
	midi_dict[(1,i)] = 0
	
#playback control
midi_dict[(1,24)] = 0
midi_dict[(1,25)] = 0
midi_dict[(1,26)] = 0
# rotary
#Pan update - thread
def update_pan():
	value_1 = midi_dict[(0,8+pan_offset)] # get curr pan val
	value_2 = midi_dict[(0,9+pan_offset)] # get curr pan val
	while True:
		# timer to update midi values
		r, w, x = select.select(devices, [], [], 0.01) # grab event
		for fd in r:
			if fd == rotary1fd:
				for event in devices[fd].read():
					event = evdev.util.categorize(event)
					if isinstance(event, evdev.events.RelEvent):
						old_val = value_1
						value_1 = value_1 + event.event.value #add and then send
						if value_1 >= 127:
							value_1 = 127
						elif value_1 <= 0:
							value_1 = 0
						pan_msg = Message('control_change', channel=0, control=8+pan_offset, value=value_1, time=0)
						outport.send(pan_msg)
			else: 
				midi_dict[(0,8+pan_offset)] = value_1
			if fd == rotary2fd:
				for event in devices[fd].read():
					event = evdev.util.categorize(event)
					if isinstance(event, evdev.events.RelEvent):
						value_2 = value_2 + event.event.value
						#print(event.event.value)
						if value_2 >= 127:
							value_2 = 127
						elif value_2 <= 0:
							value_2 = 0
						pan_msg = Message('control_change', channel=0, control=9+pan_offset, value=value_2, time=0)
						midi_dict[(0,9+pan_offset)] = value_2
						outport.send(pan_msg)
			else: midi_dict[(0,9+pan_offset)] = value_2
		time.sleep(0.01)
						# send midimessage			
#TRANSMIT/RECEIVING FADER info
receiving = False #global var to check
GPIO.setup(5, GPIO.IN, pull_up_down=GPIO.PUD_UP)	
def update_receiving(channel):
	global receiving
	receiving = not receiving
GPIO.add_event_detect(5, GPIO.RISING, callback=update_receiving, bouncetime=200)

#get faders volume from board
def update_fader_1():
	volume_2 = midi_dict[(0,1+fader_offset)]
	volume_new = get_fader_2()
	if volume_new != volume_2:
		volume_2 = volume_new
		midi_dict[(0,fader_offset+1)] = volume_2
		volume_msg = Message('control_change', channel=0, control=1+fader_offset, value=volume_2, time=0)
		outport.send(volume_msg)
	volume_1 = midi_dict[(0,fader_offset)]
	volume_new = get_fader_1()
	if volume_new != volume_1:
		volume_1 = volume_new
		midi_dict[(0,fader_offset)] = volume_1
		volume_msg = Message('control_change', channel=0, control=fader_offset, value=volume_1, time=0)
		outport.send(volume_msg)
		


#send button midi
def update_button(channel):
	chan,note = button_dict[channel]
	msg = Message('control_change', channel=chan, control=note+button_offset, value=127, time=0)
	outport.send(msg)
stopButton = False
def setStopButton():
    global stopButton
    stopButton = False
    

def update_playback(channel):
	chan,note = playback_dict[channel]
	global stopButton
	if note == 25:
	    stopButton = True
	    threading.Timer(0.35, lambda: setStopButton()).start()
	    
	msg = Message('control_change', channel=chan, control=note, value=127, time=0)
	outport.send(msg)

# much more efficient
for i, _ in button_dict.items():
	GPIO.setup(i, GPIO.IN, pull_up_down=GPIO.PUD_UP)	
	GPIO.add_event_detect(i, GPIO.RISING, callback=update_button, bouncetime=250)

for i, _ in playback_dict.items():
	GPIO.setup(i, GPIO.IN, pull_up_down=GPIO.PUD_UP)	
	GPIO.add_event_detect(i, GPIO.RISING, callback=update_playback, bouncetime=250)

#for mute: receive from chan 2 note 0
def receive_midi():
	# get midi info
	while True:
		msg = inport.poll()
		if msg is not None:
			msg = msg.hex().split()
			cc = int(msg[0], 16)
			if cc < 178 and cc < 0xF0: #filter messages
				cc -= 176
				note = int(msg[1], 16)
				val = int(msg[2], 16)
				midi_dict[(cc,note)] = val
				#print (str(cc) + " " + str(note) + " " + str(val)) #for debugging

def fader1_move_up(dc):
	pwm25.start(dc)
	#push all the way up
	GPIO.output(AI2, GPIO.HIGH)
	GPIO.output(AI1, GPIO.LOW)
def fader1_move_down(dc):
	pwm25.start(dc)
	#push all the way down
	GPIO.output(AI2, GPIO.LOW)
	GPIO.output(AI1, GPIO.HIGH)
def fader2_move_up(dc):
	pwm13.start(dc)
	#push all the way up
	GPIO.output(BI2, GPIO.HIGH)
	GPIO.output(BI1, GPIO.LOW)
def fader2_move_down(dc):
	pwm13.start(dc)
	#push all the way down
	GPIO.output(BI2, GPIO.LOW)
	GPIO.output(BI1, GPIO.HIGH)
		
# given a midi value it will go that spot
def receive_fader_1(move_val,move_time):
	diff = abs(get_fader_1() - midi_dict[(0,fader_offset)]) > 4
	start = time.time()	
	if midi_dict[(0,fader_offset)] > get_fader_1():
		while (time.time() - start < move_time) and midi_dict[(0,fader_offset)] - get_fader_1() > 4:
			fader1_move_up(52)
	elif midi_dict[(0,fader_offset)] < get_fader_1():
		while (time.time() - start < move_time) and get_fader_1() - midi_dict[(0,fader_offset)] > 4:
			fader1_move_down(52)
	pwm25.ChangeDutyCycle(0)
def receive_fader_2(move_val, move_time):
	diff = abs(get_fader_2() - midi_dict[(0,1)]) > 3
	start = time.time()	
	if midi_dict[(0,1+fader_offset)]  > get_fader_2():
		while (time.time() - start < move_time) and (midi_dict[(0,1+fader_offset)] - get_fader_2() > 4):
			fader2_move_up(52)
	elif midi_dict[(0,1+fader_offset)]  < get_fader_2():
		while (time.time() - start < move_time) and (get_fader_2() - midi_dict[(0,1+fader_offset)]) > 4:
			fader2_move_down(52)
	pwm13.ChangeDutyCycle(0)
	#fine_tune(move_val)	
def fine_tune_1(move_val):
	start = time.time()	
	if move_val > get_fader_1():
		while (time.time() - start < 10) and (get_fader_1() > move_val):
			fader1_move_up(40)
	elif move_val < get_fader_1():
		while (time.time() - start < 10) and (get_fader_1() < move_val):
			fader1_move_down(40)
	pwm25.stop()
def fine_tune_2(move_val):
	start = time.time()	
	if move_val > get_fader_1():
		while (time.time() - start < 10) and (get_fader_1() > move_val):
			fader1_move_up(40)
	elif move_val < get_fader_1():
		while (time.time() - start < 10) and (get_fader_1() < move_val):
			fader1_move_down(40)
	pwm25.stop()

#Colours
WHITE = (255,255,255)
GRAY = (105,105,105)
BLACK = (0,0,0)
RED = (255,0,0)
LIGHT_GREY = (211,211,211)

#init
pygame.init()
lcd = pygame.display.set_mode((640, 480))
#offset from left
x_offset = 120 
y_offset = 120

lcd.fill(BLACK)

#Fonts
font_big = pygame.font.Font(None, 50)
font_small = pygame.font.Font(None, 25)
#global vars
code_run = True
#button code
touch_buttons = {'Quit':(260,200)}

for k,v in touch_buttons.items():
    text_surface = font_big.render('%s'%k, True, WHITE)
    rect = text_surface.get_rect(center=v)
    lcd.blit(text_surface, rect)
    
# Track s:
track1_xc = 10 + x_offset
track1_y = 165 + y_offset
track1_buttons = {'M' : (track1_xc, track1_y+25), 'S' : (track1_xc, track1_y + 50), 'R' : (track1_xc, track1_y + 75)}

# display track val
#display volume level
#display pan real val
pan1_pos = 10 + x_offset + 1
def draw_track1():
    #pan 
    #L -> 0,63, C = 64, R: 65-127
    top_x = 10
    value_1 = midi_dict[(0,8+pan_offset)]
    if value_1 > 64:
        pan_val = value_1-63
        track1_pan = Rect((pan1_pos, y_offset-15), (int(pan_val/7),25))
        pan_val = str(min(50, pan_val))+"R"
        pygame.draw.rect(lcd, RED, track1_pan)
    elif value_1 < 64:
        pan_val = (value_1-63)
        track1_pan = Rect((pan1_pos, y_offset-15), (int((pan_val)/7), 25))
        pan_val = str(min(50, -pan_val)) + "L"
        pygame.draw.rect(lcd, RED, track1_pan)
    else: pan_val = "C"
        
    #Draw pan val
    text_surface = font_small.render('%s'%value_1, True, WHITE)
    rect = text_surface.get_rect(center=(pan1_pos, y_offset))
    lcd.blit(text_surface, rect)
    
    #vu meter
    rectHeight = midi_dict[(0,fader_offset)]
    top_y = 137-rectHeight + y_offset
    track1_outline = Rect((x_offset,8+y_offset), (20, 127+5))
    pygame.draw.rect(lcd, LIGHT_GREY, track1_outline)
    track1_meter = Rect((2+x_offset,top_y), (16, rectHeight))
    pygame.draw.rect(lcd, GRAY, track1_meter)
    
    # draw volume
    text_surface = font_small.render('%s'%midi_dict[(0,fader_offset)], True, WHITE)
    rect = text_surface.get_rect(center=(track1_xc, track1_y))
    lcd.blit(text_surface, rect)
    
    #draw track number
    text_surface = font_small.render('%s'%str(fader_offset+1), True, GRAY)
    rect = text_surface.get_rect(center=(track1_xc, track1_y + 100))
    lcd.blit(text_surface, rect)
    
    states = [127-midi_dict[(1,button_offset)], midi_dict[(1,8+button_offset)], midi_dict[(1,16+button_offset)]]
    for (k,v), state in zip(track1_buttons.items(), states):
        # CHECK IF armed
        color = RED if state == 127 else WHITE
        text_surface = font_small.render('%s'%k, True, color)
        rect = text_surface.get_rect(center=v)
        lcd.blit(text_surface, rect)
        
track2_xc = 46 + x_offset
track2_y = 165 + y_offset
track2_buttons = {'M' : (track2_xc, track2_y + 25), 'S' : (track2_xc, track2_y + 50), 'R' : (track2_xc, track2_y + 75)}
top_x_2 = 36
pan1_pos = 10 + x_offset + 1
# get all track vals from midi dict
def draw_track2():
    value_2 = midi_dict[(0,9+pan_offset)]
    if value_2 > 64:
        pan_val = value_2-63
        track2_pan = Rect((track2_xc-1, y_offset-15), (int(pan_val/7), 25))
        pan_val = str(min(50, pan_val))+"R"
        pygame.draw.rect(lcd, RED, track2_pan)
    elif value_2 < 64:
        pan_val = (value_2-63)
        track2_pan = Rect((track2_xc-1, y_offset-15), (int((pan_val)/7), 25))
        pan_val = str(min(50, -pan_val)) + "L"
        pygame.draw.rect(lcd, RED, track2_pan)
    else: pan_val = "C"
    
    #Draw pan val
    text_surface = font_small.render('%s'%value_2, True, WHITE)
    rect = text_surface.get_rect(center=(track2_xc, y_offset))
    lcd.blit(text_surface, rect)
        
    #vu meter
    rectHeight = midi_dict[(0,1+fader_offset)]
    top_y = 137-rectHeight + y_offset
    
    track2_outline = Rect((track2_xc-12,8+y_offset), (20, 127+5))
    pygame.draw.rect(lcd, LIGHT_GREY, track2_outline)
    
    text_surface = font_small.render('%s'%rectHeight, True, WHITE)
    rect = text_surface.get_rect(center=(track2_xc, track2_y))
    lcd.blit(text_surface, rect)
    
    track2_meter = Rect((track2_xc-10,top_y), (16, rectHeight))
    pygame.draw.rect(lcd, GRAY, track2_meter)
    lcd.blit(text_surface, rect)
    
    #draw track number
    text_surface = font_small.render('%s'%str(fader_offset+2), True, GRAY)
    rect = text_surface.get_rect(center=(track2_xc, track2_y + 100))
    lcd.blit(text_surface, rect)
    
    states = [127-midi_dict[(1,1+button_offset)], midi_dict[(1,8+1+button_offset)], midi_dict[(1,16+1+button_offset)]]
    for (k,v), state in zip(track2_buttons.items(), states):
        color = RED if state == 127 else WHITE
        text_surface = font_small.render('%s'%k, True, color)
        rect = text_surface.get_rect(center=v)
        lcd.blit(text_surface, rect)

        
#playback
playback_buttons = {'Play' : (100+x_offset, 20+y_offset), 'Stop' : (160+x_offset, 20+y_offset), 'Record' : (220+x_offset, 20+y_offset)}
back_next_buttons = {'Receiving' : (130+x_offset, 80+y_offset), 'Next' : (220+x_offset, 80+y_offset)}

def draw_playback():
    states = [midi_dict[(1,24)], stopButton, midi_dict[(1,26)]]
    
    for (k,v), state in zip(playback_buttons.items(), states):
        color = RED if state == 127 or state is True else WHITE
        text_surface = font_small.render('%s'%k, True, color)
        rect = text_surface.get_rect(center=v)
        lcd.blit(text_surface, rect)
        
# add next button 
def draw_next_back():
    state = [receiving, next_pressed]
    for (k,v), state in zip(back_next_buttons.items(), state):
        color = RED if state else WHITE
        text_surface = font_small.render('%s'%k, True, color)
        rect = text_surface.get_rect(center=v)
        lcd.blit(text_surface, rect)

# Init before loop
#thread for receving midi
midithread = threading.Thread(target=receive_midi)
midithread.start()
rotarythread = threading.Thread(target=update_pan)
rotarythread.start()

# start with resetting faders
receive_fader_1(108, 10)
fine_tune_1(108)
receive_fader_2(108, 10)
fine_tune_1(108)
print("ready")
receiving = True
startTime = time.time()

while time.time()-startTime < 5000 and code_run:
    if not receiving:
	    update_fader_1()
    else:
        t1 = threading.Thread(target=receive_fader_1,args=(midi_dict[(0,fader_offset)],.5,))
        t2 = threading.Thread(target=receive_fader_2,args=(midi_dict[(0,1+fader_offset)],.5,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    # update board    
    #Draw section
    lcd.fill(BLACK)
    #tracks
    draw_track1()
    draw_track2()
    #playback
    draw_playback()
    draw_next_back()
    #render
    pygame.display.flip()
    time.sleep(0.001)
midithread.join()
rotarythread.join()
#stop
pwm25.stop()
pwm13.stop()
pygame.quit()        
GPIO.cleanup()
