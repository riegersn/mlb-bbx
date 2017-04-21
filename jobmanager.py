import threading
import mc

''' 
Boxee Job Manager
An easily extensible threaded job manager that works in Boxee.
 
Written by /rob, 9 March 2011

Usage:
 

Examples:

Instantiate object:
myJobManager = BoxeeJobManager()

Process job queue every 30 seconds (instead of default 10):
myJobManager = BoxeeJobManager(30)

Add job to Job Manager:

myJob = BoxeeJob()
myJobManager.addJob(myJob)

Start Job Manager:
myJobManager.start()
'''


'''
Job Manager Object
'''
class BoxeeJobManager(threading.Thread):
    def __init__(self, interval=10, limit=18000):
        self.jobs = []
        self.elapsed = 0
        self.fault = False
        self.timer = threading.Event()
        self.interval = interval
        self.limit = limit
        threading.Thread.__init__(self)
        self.log("Initialized.")
    
    def stop(self):
        self.log("Stop command received.")
        self.fault = True
        return self.fault

    def run(self):
        # Main loop
        while self.fault is False:
            self.timer.wait(self.interval)
            self.elapsed = self.elapsed + self.interval
            try:
                self.process()
            except Exception, e:
                self.stop()
                raise JobError("Encountered running job queue.", e)
            self.check()
            # Hard limit on length of Job Manager (default five hours)
            if self.elapsed == self.limit:
                self.stop() 

    def process(self):
        # Process job quue
        if self.jobs:
            for job in self.jobs:
                if job.elapsed >= job.interval:
                    self.log("Processing job: %s" % (job.name))
                    try:
                        job.process()
                        job.elapsed = 0
                    except Exception, e:
                        raise JobError("Encountered error with job: %s" % (job.name), e)
                else:
                    job.elapsed = job.elapsed + self.interval
                    self.log("Skipping job: %s" % (job.name))
    
    def addJob(self, boxee_job):
        self.log("Adding new job: %s" % (boxee_job.name))
        return self.jobs.append(boxee_job)
    
    def check(self):
        # Extend this function to run your own check to see if loop should keep running.
        return
    
    def log(self, message):
        mc.LogDebug("BoxeeJobManager: %s" % (str(message)))

    def error(self, message):
        mc.LogError("BoxeeJobManager: %s" % (str(message)))
        
        
'''
Object for Jobs

Extend this object and pass to JobManager object to queue up the job.
'''
class BoxeeJob(object):
    def __init__(self, name, interval=10):
        self.name = name   
        self.interval = interval
        self.elapsed = 0
    
    def run(self):
        # Error-safe wrapper for user-defined job logic
        try:
            self.process()
        except Exception, e:
            raise JobError("%s failed:" % (job.name), e)
        
    def process(self):
        '''
        Main function launched with each job.
        '''
        return
    
    def log(self, message):
        mc.LogDebug("BoxeeJob %s: %s" % (self.name, str(message)))

    def error(self, message):
        mc.LogError("BoxeeJob %s: %s" % (self.name, str(message)))


'''
Boxee Job Manager Exception
'''
class JobError(Exception):
    def __init__(self, message, e):
        Exception.__init__(self, message)
        self.log(message, e)
    
    def log(self, message, e):
        return mc.LogError("BoxeeJobManager: %s! %s" % (message, str(e)))