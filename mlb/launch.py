#
# MLB launch script for Boxee Box
# Written by Shawn Rieger
#

import tracker
from mlb import MLB
import cgi
import sys
import mc

mlb = MLB()
mc.ShowDialogWait()

args = False
myTracker = tracker.Tracker()
myTracker.trackView("Launch")

if sys.argv[1]:
   args = cgi.parse_qs(sys.argv[1])

if not mlb.init(args):
   mc.HideDialogWait()
