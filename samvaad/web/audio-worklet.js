// Runs in the browser's audio thread: converts microphone audio to 16 kHz mono
// int16 and hands it over in 100 ms blocks.
class SamvaadCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;
    this.sum = 0;
    this.count = 0;
    this.block = new Int16Array(1600);
    this.n = 0;
  }

  push(value) {
    const v = Math.max(-1, Math.min(1, value));
    this.block[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
    if (this.n === this.block.length) {
      this.port.postMessage(this.block.buffer.slice(0));
      this.n = 0;
    }
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const ch = input[0];
    if (this.ratio === 1) {
      for (let i = 0; i < ch.length; i++) this.push(ch[i]);
      return true;
    }
    // Box-filter decimation: average the samples that fall into each output sample.
    for (let i = 0; i < ch.length; i++) {
      this.sum += ch[i];
      this.count++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        this.push(this.sum / this.count);
        this.sum = 0;
        this.count = 0;
      }
    }
    return true;
  }
}

registerProcessor("samvaad-capture", SamvaadCapture);
