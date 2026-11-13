import os

# The app checks GitHub for a newer release on start; tests never reach the network.
os.environ["UPDATE_CHECK"] = "0"

# R10: the TUS journal auto-import thread reads the real NinjaTrader folder; tests call it directly.
os.environ["TCC_TUS_AUTO_IMPORT"] = "0"
