import multiprocessing
from moviepy.editor import VideoFileClip, concatenate_videoclips
import numpy as np

def is_black_frame(frame, threshold=120):
    return frame.max() <= threshold

def is_black_frame_avg(frame, threshold=10):
    return np.mean(frame) <= threshold

def process_clip(args):
    start_time, end_time, file_path, i = args
    video = VideoFileClip(file_path)
    clip = video.subclip(start_time, end_time)
    clip.write_videofile(f"fg5-{i}.mp4")

def is_grey_frame(frame, threshold=10):
    frame_gray = np.dot(frame[..., :3], [0.2989, 0.5870, 0.1140])
    std_dev = np.std(frame_gray)
    return std_dev <= threshold

def divide_video(file_path):
    video = VideoFileClip(file_path)
    duration = video.duration
    num_processes = 10
    pool = multiprocessing.Pool(processes=num_processes)
    tasks = []
    start_time = 0
    i = 0
    frame_index = 0
    skip_frames = 0  # New variable to skip frames
    for frame in video.iter_frames():
        # print current seconds, every 25 frames
        if frame_index % 15 == 0:
            print(frame_index / video.fps)
        if skip_frames > 0:  # If skip_frames is greater than 0, decrement it and continue
            skip_frames -= 1
            frame_index += 1
            continue
        if is_black_frame_avg(frame):
            print("Black frame detected")
            end_time = frame_index / video.fps
            if end_time > start_time:
                tasks.append((start_time, end_time, file_path, i))
                i += 1
            start_time = end_time
            skip_frames = 50  # Set skip_frames to 50 when a black frame is detected
        frame_index += 1
    print("Total clips:", i)
    if start_time < duration:
        tasks.append((start_time, duration, file_path, i))
    pool.map(process_clip, tasks)
    pool.close()
    pool.join()

if __name__ == '__main__':
    divide_video("H:\\bup82623\\Downloads\\fg5.mp4")