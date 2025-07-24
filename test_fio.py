#!/usr/bin/env python3
"""
Quick test to check FIO4 and FIO5 states
"""

import u3

def test_fio_states():
    try:
        lj = u3.U3()
        print('Testing FIO4 and FIO5 states:')
        
        # Read FIO4
        state4 = lj.getFeedback(u3.BitStateRead(4))[0]
        print(f'FIO4: {"HIGH" if state4 else "LOW"}')
        
        # Read FIO5
        state5 = lj.getFeedback(u3.BitStateRead(5))[0]
        print(f'FIO5: {"HIGH" if state5 else "LOW"}')
        
        lj.close()
        
    except Exception as e:
        print(f'Error: {e}')

if __name__ == "__main__":
    test_fio_states()
