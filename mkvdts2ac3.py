#!/usr/bin/env python

import os
import re
import shutil
import subprocess
import sys
import tempfile
from ConfigParser import SafeConfigParser
from optparse import OptionParser, OptionGroup

#Script defaults
DEFAULTS = SafeConfigParser({
    'All': 'False',
    'MarkDefault': 'False',
    'KeepExternal': 'False',
    'Force': 'False',
    'Initial': 'False',
    'KeepDTS': 'False',
    'LeaveNew': 'False',
    'NoDTS': 'False',
    'CopyNew': 'False',
    'Priority': '0',
    'WorkingDirectory': tempfile.gettempdir(),

    'CustomAften': [],
    'CustomDcadec': [],

    'Color': 'True',
    'Quiet': 'False',
    'Verbose': 'False',
})
DEFAULTS.add_section('Main')
#Load user-defined defaults from a config file in their home directory
DEFAULTS.read(os.path.join(os.path.expanduser('~'), '.mkvdts2ac3.ini'))


#Argument parsing
version = '''
mkvdts2ac3-2.0.0pre - by Jake Wharton <jakewharton@gmail.com> and
                         Chris Hoekstra <chris.hoekstra@gmail.com>
'''
parser = OptionParser(usage="Usage: %prog [options] file1 [... fileN]", version=version)

group = OptionGroup(parser, "Configuration Options")
group.add_option('-a', '--all', dest='parse_all', action='store_true', default=DEFAULTS.getboolean('Main', 'All'), help='Parse all DTS tracks in MKV.')
group.add_option('-c', '--custom', dest='custom_title', default=None, help='Specify custom AC3 track title.')
group.add_option('-d', '--default', dest='mark_default', action='store_true', default=DEFAULTS.getboolean('Main', 'MarkDefault'), help='Mark AC3 track as default.')
group.add_option('-e', '--external', dest='keep_external', action='store_true', default=DEFAULTS.getboolean('Main', 'KeepExternal'), help='Leave generated AC3 track out of file. Does not modify the original MKV.')
group.add_option('-f', '--force', dest='force_process', action='store_true', default=DEFAULTS.getboolean('Main', 'Force'), help='Force processing when existing AC3 track is detected.')
group.add_option('-i', '--initial', dest='is_initial', action='store_true', default=DEFAULTS.getboolean('Main', 'Initial'), help='New AC3 track will be first in file.')
group.add_option('-k', '--keep', dest='keep_dts', action='store_true', default=DEFAULTS.getboolean('Main', 'KeepDTS'), help='Retain external DTS track (implies -n).')
group.add_option('-l', '--leave', dest='leave_new', action='store_true', default=DEFAULTS.getboolean('Main', 'LeaveNew'), help='Leave new MKV in working directory.')
group.add_option('-n', '--no-dts', dest='no_dts', action='store_true', default=DEFAULTS.getboolean('Main', 'NoDTS'), help='Do not retain DTS track.')
group.add_option('--new', dest='copy_new', action='store_true', default=DEFAULTS.getboolean('Main', 'CopyNew'), help='Do not copy over original. Create new adjacent file.')
group.add_option('-p', dest='priority', default=DEFAULTS.getint('Main', 'Priority'), help='Niceness priority.')
group.add_option('-t', '--track', dest='track_id', default=None, help='Specify alternate DTS track ID.')
group.add_option('-w', '--wd', dest='working_dir', default=DEFAULTS.get('Main', 'WorkingDirectory'), help='Specify working directory for temporary files.')
parser.add_option_group(group)

group = OptionGroup(parser, 'Subprocess Options')
group.add_option('-A', dest='custom_aften', action='append', default=DEFAULTS.get('Main', 'CustomAften'), help='Pass custom arguments to aften.')
group.add_option('-D', dest='custom_dcadec', action='append', default=DEFAULTS.get('Main', 'CustomDcadec'), help='Pass custom arguments to dcadec.')
parser.add_option_group(group)

group = OptionGroup(parser, "Testing Options")
group.add_option('--test', dest='is_test', action='store_true', default=False, help='Print commands only, execute nothing.')
group.add_option('--debug', dest='is_debug', action='store_true', default=False, help='Print commands and pause before executing each.')
parser.add_option_group(group)

group = OptionGroup(parser, "Display Options")
group.add_option('-m', '--no-color', dest='is_color', action='store_false', default=DEFAULTS.getboolean('Main', 'Color'), help='Do not use colors (monochrome).')
group.add_option('-q', '--quiet', dest='is_quiet', action='store_true', default=DEFAULTS.getboolean('Main', 'Quiet'), help='Output nothing to the terminal.')
group.add_option('-v', '--verbose', dest='is_verbose', action='store_true', default=DEFAULTS.getboolean('Main', 'Verbose'), help='Turn on verbose output.')
parser.add_option_group(group)

options, mkvfiles = parser.parse_args()

#Script header
if not options.is_quiet:
    parser.print_version()



#Color functions
red    = lambda text: ('\033[1;31m%s\033[0m' % text) if options.is_color else text
green  = lambda text: ('\033[1;32m%s\033[0m' % text) if options.is_color else text
blue   = lambda text: ('\033[1;34m%s\033[0m' % text) if options.is_color else text
yellow = lambda text: ('\033[1;33m%s\033[0m' % text) if options.is_color else text

def debug(text, *args):
    if options.is_verbose:
        print yellow('DEBUG: ') + text % args
def info(text, *args):
    if not options.is_quiet:
        print blue('INFO: ') + text % args
def warn(text, *args):
    if not options.is_quiet:
        print red('WARNING: ') + text % args
def error(text, *args):
    if not options.is_quiet:
        print red('ERROR: ') + text % args



#Check argument restrictions
exit = False
if options.keep_dts:
    options.no_dts = True
if options.no_dts and options.keep_external:
    error('Options `-e` and `-n` are mutually exclusive.')
    exit = True
if options.track_id and options.parse_all:
    warn('`-n %s` overrides `-a`.', options.track_id)
if options.is_quiet and options.is_verbose:
    error('Options `-q` and `-v` are mutually exclusive.')
    exit = True
if options.is_test and options.is_debug:
    error('Options `--test` and `--debug` are mutually exclusive. Try --test and -v for more information.')
    exit = True
if options.mark_default and options.keep_external:
    warn('`-e` overrides `-d`.')
if options.custom_title and options.keep_external:
    warn('`-c` is not needed with `-d`.')
if len(mkvfiles) == 0:
    error('You must include at least one file.')
    exit = True
if exit: sys.exit(1)


RE_MKVMERGE_INFO = re.compile(r'''Track ID (?P<id>\d+): (?P<type>video|audio|subtitles) \((?P<codec>[A-Z0-9_/]+)\)''')
DTS_FILE = '%s.%s.dts'
AC3_FILE = '%s.%s.ac3'
TC_FILE  = '%s.%s.tc'
NEW_FILE = '%s.new.mkv'


#Iterate over input files
for mkvfile in mkvfiles:
    info('Processing "%s"...' % mkvfile)

    #Check if the file exists
    if not os.path.isfile(mkvfile):
        error('Invalid file "%s". Skipping...', mkvfile)
        continue
    if not mkvfile.endswith('.mkv'):
        error('Does not appear to be a Matroska file. Skipping...')
        continue


    mkvpath  = os.path.dirname(mkvfile)
    mkvname  = os.path.basename(mkvfile)
    mkvtitle = mkvname[:-4] #Remove ".mkv" extension
    debug('mkvfile  = %s', mkvfile)
    debug('mkvpath  = %s', mkvpath)
    debug('mkvname  = %s', mkvname)
    debug('mkvtitle = %s', mkvtitle)


    #Get mkvmerge info and mkvinfo for the tracks
    mkvtracks = {}
    mkvmergeinfo = subprocess.Popen(['mkvmerge', '-i', mkvfile], stdout=subprocess.PIPE).communicate()[0]
    mkvinfo = subprocess.Popen(['mkvinfo', mkvfile], stdout=subprocess.PIPE).communicate()[0]
    for match in RE_MKVMERGE_INFO.finditer(mkvmergeinfo):
        matchdict = match.groupdict()
        id = matchdict.pop('id')
        debug('Found track %s: %s.', id, matchdict)
        mkvtracks[id] = matchdict

        #TODO: parse mkvinfo
        mkvtracks[id]['dts_lang'] = 'und'
        mkvtracks[id]['dts_name'] = None


    #Get DTS tracks which need parsing
    parsetracks = {}
    if options.track_id is not None:
        if track_id not in mkvtracks.keys():
            error('Explicitly defined track id does not exist in file.')
            continue
        if mkvtracks[options.track_id]['codec'] != 'A_DTS':
            error('Explicitly defined track id is not a DTS track.')
            continue
        parsetracks[options.track_id] = mkvtracks[options.track_id]
        debug('Using argument specified track id %s.', options.track_id)
    elif options.parse_all:
        parsetracks = dict((id, info) for id, info in mkvtracks.iteritems() if info['codec'] == 'A_DTS')
        if len(parsetracks) == 0:
            error('No DTS tracks found in file.')
            continue
        debug('Using track %s %s.', 'id' if len(parsetracks) == 1 else 'ids', ', '.join(parsetracks.keys()))
    else:
        tracks = [id for id in mkvtracks.keys() if mkvtracks[id]['codec'] == 'A_DTS']
        if len(tracks) == 0:
            error('No DTS tracks found in file.')
            continue
        parsetracks[tracks[0]] = mkvtracks[tracks[0]]
        debug('Using track id %s.', tracks[0])


    #Extract timecodes for the tracks
    info('Extracting timecodes...')
    cmd = ['mkvextract', 'timecodes_v2', mkvfile]
    for track in parsetracks.keys():
        tc_file = parsetracks[track]['tc_file'] = os.path.join(options.working_dir, TC_FILE % (mkvtitle, track))
        cmd.append('%s:%s' % (track, tc_file))
        debug('Track %s to "%s".', track, tc_file)
    if not options.is_test:
        subprocess.Popen(cmd).wait()

    #Parse timecodes for each track
    for track in parsetracks.keys():
        if not options.is_test:
            f = open(parsetracks[track]['tc_file'])
            f.readline()
            delay = f.readline().strip()
            f.close()
        else:
            delay = 0

        parsetracks[track]['dts_delay'] = delay
        debug('Track %s delay = %sms.' % (track, delay))

    #Extract DTS tracks
    info('Extracting DTS tracks...')
    cmd = ['mkvextract', 'tracks', mkvfile]
    for track in parsetracks.keys():
        dts_file = parsetracks[track]['dts_file'] = os.path.join(options.working_dir, DTS_FILE % (mkvtitle, track))
        cmd.append('%s:%s' % (track, dts_file))
        debug('Track %s to "%s".', track, dts_file)
    if not options.is_test:
        subprocess.Popen(cmd).wait()

    #Convert DTS to AC3
    info('Converting DTS to AC3...')
    for track in parsetracks.keys():
        ac3_file = parsetracks[track]['ac3_file'] = os.path.join(options.working_dir, AC3_FILE % (mkvtitle, track))
        debug('Track %s to "%s".', track, ac3_file)

        #Assemble dcadec command
        dcadec = ['dcadec']
        pairs = {'-o': 'wavall'}
        for pair in options.custom_dcadec:
            arg, value = pair.split('=', 1)
            pairs[arg] = value
            debug('Custom dcadec args: %s %s.' % (arg, value))
        for arg, value in pairs.iteritems():
            dcadec.append(arg)
            dcadec.append(value)
        dcadec.append(parsetracks[track]['dts_file'])

        #Assemble aften command
        aften = ['aften']
        for pair in options.custom_aften:
            arg, value = pair.split('=', 1)
            aften.append(arg)
            aften.append(value)
            debug('Custom aften args: %s %s.' % (arg, value))
        aften.append('-')
        aften.append(parsetracks[track]['ac3_file'])

        #Do the conversion
        if not options.is_test:
            dcadec_cmd = subprocess.Popen(dcadec, stdout=subprocess.PIPE)
            aften_cmd  = subprocess.Popen(aften, stdin=dcadec_cmd.stdout).wait()

            #Get DTS and AC3 file sizes
            parsetracks[track]['dts_size'] = os.path.getsize(parsetracks[track]['dts_file'])
            parsetracks[track]['ac3_size'] = os.path.getsize(ac3_file)

            #Delete DTS files
            if not options.keep_dts:
                os.remove(parsetracks[track]['dts_file'])

    if options.keep_external:
        info('Copying AC3 files to MKV directory...')
        for track, trackinfo in parsetracks.iteritems():
            debug('Track %s from "%s" to "%s".', track, trackinfo['ac3_file'], mkvpath)
            if not options.is_test:
                shutil.copy2(trackinfo['ac3_file'], mkvpath)
    else:
        info('Muxing new %s together with original...' % 'track' if len(parsetracks) == 1 else 'tracks')

        #Start the build the main remux command
        cmd = ['mkvmerge', '-q']

        if options.is_initial:
            #Put AC3 track(s) first in the file
            cmd.append('--track-order')
            order = ['0:1']
            for i in range(len(parsetracks)):
                i += 1
                order.append('%s:0' % i)
            cmd.append(','.join(order))

        #Declare output file
        new_file = NEW_FILE % mkvtitle
        cmd.append('-o')
        cmd.append(new_file)

        if options.no_dts:
            #Find non-DTS tracks (if any) to save
            save_tracks = [track for track, trackinfo in mkvtracks if track not in parsetracks.keys() and trackinfo['codec'].startswith('A_')]
            if save_tracks:
                cmd.append('-a')
                cmd.append(','.join(save_tracks))
            else:
                cmd.append('-A')

        #Add original MKV file
        cmd.append(mkvfile)

        for track, trackinfo in parsetracks.iteritems():
            if options.mark_default:
                #Mark first new AC3 track as default
                cmd.append('--default-track')
                cmd.append(0)
                options.mark_default = False #So this only fires once

            #Copy over the languages from respective DTS tracks
            cmd.append('--language')
            cmd.append('0:%s' % trackinfo['dts_lang'])

            #Add delay if there was one on the original DTS
            delay = int(trackinfo['dts_delay'])
            if delay > 0:
                cmd.append('--sync')
                cmd.append('0:%s' % delay)

            #Copy the track name if one existed on the DTS
            if trackinfo['dts_name']:
                cmd.append('--track-name')
                cmd.append('0:"%s"' % trackinfo['dts_name'])

            #Append this AC3 file
            cmd.append(trackinfo['ac3_file'])

        #Run main remux
        debug('Main command: ' + ' '.join(cmd))
        if not options.is_test:
            subprocess.Popen(cmd).wait()

        #Delete AC3 files
        for track in parsetracks.keys():
            debug('Deleting "%s"...', parsetracks[track]['ac3_file'])
            if not options.is_test:
                os.remove(parsetracks[track]['ac3_file'])

        #Copy the temporary new file back to source directory, overwriting if not adjacent
        if options.copy_new:
            info('Moving new MKV file next to the old MKV file...')
            dest_file = os.path.join(mkvpath, NEW_FILE % mkvtitle)
        else:
            info('Moving new MKV file over the old MKV file...')
            dest_file = mkvfile
        debug('Copying "%s" to "%s"...' % (new_file, dest_file))
        if not options.is_test:
            shutil.copyfile(new_file, dest_file)

        #Delete the temporary new file if not marked to keep
        if not options.leave_new:
            debug('Deleting temporary MKV file.')
            if not options.is_test:
                os.remove(new_file)