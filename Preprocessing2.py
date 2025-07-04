import pickle
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
import biosppy.signals.tools as st
import numpy as np
import os
import wfdb
from biosppy.signals.ecg import correct_rpeaks, hamilton_segmenter
from scipy.signal import medfilt
from tqdm import tqdm
import neurokit2 as nk

base_dir = "dataset"

fs = 100
sample = fs * 60  

before = 2  
after = 2  
hr_min = 20
hr_max = 300

num_worker = 35  


def worker(name, labels):
    X = []
    y = []
    groups = []
    signals = wfdb.rdrecord(os.path.join(base_dir, name), channels=[0]).p_signal[:, 0]    
    for j in tqdm(range(len(labels)), desc=name, file=sys.stdout):
        if j < before or \
                (j + 1 + after) > len(signals) / float(sample):        
            continue
        signal = signals[int((j - before) * sample):int((j + 1 + after) * sample)]      
        signal, _, _ = st.filter_signal(signal, ftype='FIR', band='bandpass', order=int(0.3 * fs),
                                        frequency=[3, 45], sampling_rate=fs)       
        rpeaks, = hamilton_segmenter(signal, sampling_rate=fs)
        rpeaks, = correct_rpeaks(signal, rpeaks=rpeaks, sampling_rate=fs, tol=0.1)  
        if len(rpeaks) / (1 + after + before) < 40 or \
                len(rpeaks) / (1 + after + before) > 200:  
            continue

        rri_tm, rri_signal = rpeaks[1:] / float(fs), np.diff(rpeaks) / float(fs)    
        rri_signal = medfilt(rri_signal, kernel_size=3)        
        ampl_tm, ampl_signal = rpeaks / float(fs), signal[rpeaks]  
        hr = 60 / rri_signal         
 
        try:
            # HRV 特征（时域+频域+非线性）
            hrv_features = nk.hrv(rpeaks, sampling_rate=100, show=False)
            hrv_dict = {}
            for col in hrv_features.columns:
                hrv_dict[col.lower()] = hrv_features[col].values[0]  
        except Exception as e:
            hrv_dict = {col.lower(): 0.0 for col in hrv_features.columns}  
            print("HRV 计算失败:", str(e))
        if np.all(np.logical_and(hr >= hr_min, hr <= hr_max)):
            X.append({
                "rri": (rri_tm, rri_signal),        
                "amplitude": (ampl_tm, ampl_signal),   
                "hrv": hrv_dict                      
            })
            y.append(0. if labels[j] == 'N' else 1.)
            groups.append(name)
        if not np.all(np.logical_and(hr >= hr_min, hr <= hr_max)):
            continue
    return X, y, groups


if __name__ == "__main__":
    apnea_ecg = {}

    names = [
        "a01","a02", "a03", "a04",
         "a05", "a06", "a07", "a08", "a09", "a10",
        "a11", "a12", "a13", "a14", "a15", "a16", "a17", "a18", "a19", "a20",
        "b01", "b02", "b03", "b04", "b05",
        "c01", "c02", "c03", "c04", "c05", "c06", "c07", "c08", "c09", "c10"
    ]

    o_train = []
    y_train = []
    groups_train = []
    print('Training...')
    with ProcessPoolExecutor(max_workers=num_worker) as executor:
        task_list = []
        for i in range(len(names)):
            labels = wfdb.rdann(os.path.join(base_dir, names[i]), extension="apn").symbol
            task_list.append(executor.submit(worker, names[i], labels))

        for task in as_completed(task_list):
            X, y, groups = task.result()
            o_train.extend(X)
            y_train.extend(y)
            groups_train.extend(groups)

    print()

    answers = {}
    with open(os.path.join(base_dir, "event-2-answers"), "r") as f:
        for answer in f.read().split("\n\n"):
            answers[answer[:3]] = list("".join(answer.split()[2::2]))

    names = [
        "x01", "x02", "x03", "x04",
         "x05", "x06", "x07", "x08", "x09", "x10",
        "x11", "x12", "x13", "x14", "x15", "x16", "x17", "x18", "x19", "x20",
        "x21", "x22", "x23", "x24", "x25", "x26", "x27", "x28", "x29", "x30",
        "x31", "x32", "x33", "x34", "x35"
    ]

    o_test = []
    y_test = []
    groups_test = []
    print("Testing...")
    with ProcessPoolExecutor(max_workers=num_worker) as executor:
        task_list = []
        for i in range(len(names)):
            labels = answers[names[i]]
            task_list.append(executor.submit(worker, names[i], labels))

        for task in as_completed(task_list):
            X, y, groups = task.result()
            o_test.extend(X)
            y_test.extend(y)
            groups_test.extend(groups)

    apnea_ecg = dict(o_train=o_train, y_train=y_train, groups_train=groups_train, o_test=o_test, y_test=y_test,
                     groups_test=groups_test)
    with open(os.path.join(base_dir, "apnea(hrv).pkl"), "wb") as f:
        pickle.dump(apnea_ecg, f, protocol=2)

    print("\nok!")
