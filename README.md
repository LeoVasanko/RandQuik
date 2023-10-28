# Extremely fast Cryptographically Secure RNG

I was disappointed with the sad state of random number generators. Many languages don't ship anything useful and some are stuck with whatever the OS provides. All existing implementations are slow, typically maxing out at a few hundred megabytes per second.

To give some perspective, my tool reaches 37.8 GB/s, writing /dev/null. Several gigabytes per second also on actual SSDs.

Secondly, flaws have been found in non-cryptographic algorithms, especially on Mersenne Twister. The cryptographic options are simply better, being free of such issues as sequences repeating, and additionally being, well, cryptographically secure. Surprisingly, they appear even to be faster now, so there really ought to be no reason to stick with the old.
