using System;
using System.Threading;
using System.Collections.Concurrent;

namespace HMX.HASSActronQue
{
    public partial class Que
    {

        public static bool TryEnqueueQueueCommand(QueueCommand cmd)
        {
            if (cmd == null) return false;

            lock (_oLockQueue)
            {
                // Enqueue and increment count
                _queueCommands.Enqueue(cmd);
                Interlocked.Increment(ref _queueCount);

                // Trim oldest items if we exceed the max size.
                // Doing this under _oLockQueue avoids racing with ProcessQueue which expects
                // to be the only code removing the head except for trimming here.
                while (Volatile.Read(ref _queueCount) > _iQueueMaxSize)
                {
                    if (_queueCommands.TryDequeue(out _))
                        Interlocked.Decrement(ref _queueCount);
                    else
                        break; // queue empty (race), exit
                }

                // Signal monitors waiting on queue updates (same behavior as previous code using _eventQueue)
                try { _eventQueue?.Set(); } catch { }
            }

            return true;
        }

        /// <summary>
        /// Try to dequeue a command. Returns true and sets 'cmd' if an item was available.
        /// </summary>
        public static bool TryDequeueQueueCommand(out QueueCommand cmd)
        {
            if (_queueCommands.TryDequeue(out cmd))
            {
                Interlocked.Decrement(ref _queueCount);
                return true;
            }
            cmd = null;
            return false;
        }

        /// <summary>
        /// Get current approximate queue length.
        /// </summary>
        public static int GetQueueLength() => Math.Max(0, Volatile.Read(ref _queueCount));

        /// <summary>
        /// Optionally expose a setter to tune the max size at runtime.
        /// </summary>
        public static void SetQueueMaxSize(int max)
        {
            if (max <= 0) return;
            Interlocked.Exchange(ref _iQueueMaxSize, max);
            // Optionally trim immediately if the new max is lower than current count
            lock (_oLockQueue)
            {
                while (Volatile.Read(ref _queueCount) > _iQueueMaxSize)
                {
                    if (_queueCommands.TryDequeue(out _)) Interlocked.Decrement(ref _queueCount);
                    else break;
                }
            }
        }
    }
}