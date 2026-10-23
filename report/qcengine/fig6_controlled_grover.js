// Fig. 6: one controlled Grover iteration Q = (mirror) * O_f for the tile of Fig. 2.
// Paste into QCEngine (https://oreilly-qc.github.io) and press "Run".
// Screenshot the circuit diagram at the top.
//
// Qubits: qx (0x1, 0x2), qy (0x4, 0x8) = subpixel x = 4*qy + qx
//         c  (0x10)                    = one counter qubit (the control)

qc.reset(5);
var qx = qint.new(2, 'qx');
var qy = qint.new(2, 'qy');
var c  = qint.new(1, 'c');
qc.write(0);

var pos  = 0xF;     // the four position qubits
var cbit = 0x10;    // counter control

// Phase oracle O_f, controlled by c: one phase flip per white subpixel
var white = [0, 2, 5, 7, 8, 10, 13, 15];
qc.label('oracle O_f');
for (var i = 0; i < white.length; ++i)
{
    var zeros = (~white[i]) & pos;
    if (zeros) qc.not(zeros);
    qc.cphase(180, pos | cbit);      // only this gate needs the counter control
    if (zeros) qc.not(zeros);
}

// Mirror (book's grover_iteration): H X (flip |0000>) X H, controlled by c
qc.label('mirror');
qc.hadamard(pos);
qc.not(pos);
qc.cphase(180, pos | cbit);
qc.not(pos);
qc.hadamard(pos);
qc.label('');
