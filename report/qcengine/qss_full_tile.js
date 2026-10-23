// Full QSS for one tile (t = 4 counter qubits, 8 qubits in total).
// Paste into QCEngine (https://oreilly-qc.github.io) and press "Run".
//
// The circuit is long (15 controlled Grover iterations), so it is better for
// checking the result than for a figure. Expected result for this tile (k = 8):
// the counter reads y = 4 or y = 12 (probability 1/2 each), which decodes to
// k = 8, i.e. brightness 8/16 = 0.5.

qc.reset(8);
var qx      = qint.new(2, 'qx');
var qy      = qint.new(2, 'qy');
var counter = qint.new(4, 'counter');
qc.write(0);

var pos   = 0xF;
var white = [0, 2, 5, 7, 8, 10, 13, 15];   // checkerboard tile, k = 8

function controlled_grover(cbit)
{
    for (var i = 0; i < white.length; ++i)       // oracle O_f
    {
        var zeros = (~white[i]) & pos;
        if (zeros) qc.not(zeros);
        qc.cphase(180, pos | cbit);
        if (zeros) qc.not(zeros);
    }
    qc.hadamard(pos);                            // mirror
    qc.not(pos);
    qc.cphase(180, pos | cbit);
    qc.not(pos);
    qc.hadamard(pos);
}

function swap(a, b) { qc.cnot(a, b); qc.cnot(b, a); qc.cnot(a, b); }

// Blank canvas and counter superposition
qc.label('H');
qc.hadamard(pos);
counter.hadamard();

// Counter qubit j controls Q^(2^j)
for (var j = 0; j < 4; ++j)
{
    qc.label('Q^' + (1 << j));
    var cbit = 0x10 << j;
    for (var r = 0; r < (1 << j); ++r)
        controlled_grover(cbit);
}

// Inverse QFT on the counter (same convention as the report)
qc.label('inverse QFT');
var c0 = 0x10, c1 = 0x20, c2 = 0x40, c3 = 0x80;
swap(c1, c2);
swap(c0, c3);
qc.hadamard(c0);
qc.cphase(-90, c0 | c1);
qc.hadamard(c1);
qc.cphase(-45, c0 | c2);
qc.cphase(-90, c1 | c2);
qc.hadamard(c2);
qc.cphase(-22.5, c0 | c3);
qc.cphase(-45, c1 | c3);
qc.cphase(-90, c2 | c3);
qc.hadamard(c3);
qc.label('');

// Read the counter and decode with the t = 4 lookup table
var decode = [16, 15, 14, 11, 8, 5, 2, 1, 0, 1, 2, 5, 8, 11, 14, 15];
var y = counter.read();
qc.print('readout y = ' + y + '  ->  k = ' + decode[y] +
         '  ->  brightness = ' + (decode[y] / 16) + '\n');
