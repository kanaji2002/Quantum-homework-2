// Fig. 5: four-qubit inverse QFT on the counter, written gate by gate
// (same gate order as the Qiskit version used in the report).
// Paste into QCEngine (https://oreilly-qc.github.io) and press "Run".
// Screenshot the circuit diagram at the top.

qc.reset(4);
var counter = qint.new(4, 'counter');
qc.write(0);

var c0 = 0x1, c1 = 0x2, c2 = 0x4, c3 = 0x8;

function swap(a, b)          // SWAP built from three CNOTs
{
    qc.cnot(a, b);
    qc.cnot(b, a);
    qc.cnot(a, b);
}

qc.label('bit reversal');
swap(c1, c2);
swap(c0, c3);

qc.label('H + controlled phases');
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
