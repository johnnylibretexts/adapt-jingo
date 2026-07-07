# Johnny Lingo Pronunciation Engine Notice

`johnnylingo-jingo` is a provisional pronunciation-learning SDK. It is not a
clinical, academic, hiring, certification, or high-stakes assessment tool.

The package ships calibration and vocabulary JSON assets, but it does not ship
the CTranslate2 acoustic model. Host applications must provide and verify that
external model artifact before enabling acoustic pronunciation scoring.

Default calibration remains `provisional: true`. Thresholds are
channel-sensitive and have not been validated against human tutor labels.
