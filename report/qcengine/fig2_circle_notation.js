// Fig. 2: phase-encoded tile (row 35, column 64 of the Mona Lisa), shown in circle notation.
// Paste into QCEngine (https://oreilly-qc.github.io) and press "Run".
//
// The tile is a checkerboard with k = 8 white subpixels:
//         qx=0 qx=1 qx=2 qx=3
//   qy=0   W    .    W    .
//   qy=1   .    W    .    W
//   qy=2   W    .    W    .
//   qy=3   .    W    .    W
// Subpixel index x = 4*qy + qx  ->  white x = 0, 2, 5, 7, 8, 10, 13, 15

qc.reset(4);
var qx = qint.new(2, 'qx');   // bits 0x1, 0x2  (low bits of x)
var qy = qint.new(2, 'qy');   // bits 0x4, 0x8  (high bits of x)
qc.write(0);

// Blank canvas: uniform superposition of all 16 subpixels
qc.label('blank canvas');
qx.hadamard();
qy.hadamard();
qc.label('');

// Phase oracle: one multi-controlled phase flip per white subpixel
// (the same construction as the report: X on the 0-bits, CZ on all 4 qubits, X back)
var white = [0, 2, 5, 7, 8, 10, 13, 15];
qc.label('oracle O_f');
for (var i = 0; i < white.length; ++i)
{
    var zeros = (~white[i]) & 0xF;   // qubits whose bit is 0 in x
    if (zeros) qc.not(zeros);
    qc.cphase(180, 0xF);             // flip the sign of |1111>
    if (zeros) qc.not(zeros);
}
qc.label('');

// Circle notation now shows 16 circles of equal size;
// the white subpixels (x = 0, 2, 5, 7, 8, 10, 13, 15) have phase 180 degrees.
