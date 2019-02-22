import os
import subprocess
import sidekit
import numpy as np
from tqdm import tqdm
from utils import preprocessAudioFile
import multiprocessing as mp
import numpy as np
import warnings
warnings.filterwarnings("ignore")




class SpeakerRecognizer():

    def __init__(self):
        ############ Global Variables ###########
        # self.SAMPLE_RATE = 16000
        self.NUM_CHANNELS = 2
        self.PRECISION = 16 #I mean 16-bit
        self.NUM_THREADS = mp.cpu_count() #(4 default)
        # Number of Guassian Distributions
        self.NUM_GUASSIANS = 32
        self.base_dir = "/media/anwar/E/Voice_Biometrics/SIDEKIT-1.3/py3env"
    

    def extractFeatures(self, group):
        """
        This function computes the acoustic parameters:
         -> filter banks: fb
         -> cepstral coefficients: cep
         -> log-energy: energy
         -> vad: type of voice activity detection algorithm to use.
                Can be "energy", "snr", "percentil" or "lbl".
                I chose snr (Signal-to-noise-ratio)
        for a list of audio files and save them to disk in a HDF5 format
        The process is parallelized if num_thread is higher than 1
        """
        in_files = os.listdir(os.path.join(self.base_dir, "audio", group))
        feat_dir = os.path.join(self.base_dir, "feat", group)
        # Feature extraction
        # lower_frequency: lower frequency (in Herz) of the filter bank
        # higher_frequency: higher frequency of the filter bank
        # filter_bank: type of fiter scale to use, can be "lin" or "log" (for linear of log-scale)
        # filter_bank_size: number of filters banks
        # window_size: size of the sliding window to process (in seconds)
        # shift: time shift of the sliding window (in seconds)
        # ceps_number: number of cepstral coefficients to extract

        # snr: signal to noise ratio used for "snr" vad algorithm
        # pre_emphasis: value given for the pre-emphasis filter (default is 0.97)
        # save_param: list of strings that indicate which parameters to save. The strings can be:
        # "cep" for cepstral coefficients, "fb" for filter-banks, "energy" for the log-energy, "bnf"
        # for bottle-neck features and "vad" for the frame selection labels.
        # keep_all_features: boolean, if True, all frames are writen; if False, keep only frames according to the vad label
        # NOTE: ths will create features from audio/data directory which contains all of our files
        extractor = sidekit.FeaturesExtractor(audio_filename_structure=os.path.join(self.base_dir, "audio", group, "{}"),
                                              feature_filename_structure=os.path.join(feat_dir, "{}.h5"),
                                              lower_frequency=300,
                                              higher_frequency=3400,
                                              filter_bank="log",
                                              filter_bank_size=24,
                                              window_size=0.025,
                                              shift=0.01,
                                              ceps_number=19,
                                              vad="snr",
                                              snr=40,
                                              pre_emphasis=0.97,
                                              save_param=["vad", "energy", "cep", "fb"],
                                              keep_all_features=True)

        # Prepare file lists
        # show_list: list of IDs of the show to process
        show_list = np.unique(np.hstack([in_files]))
        # channel_list: list of channel indices corresponding to each show
        channel_list = np.zeros_like(show_list, dtype = int)

        # save the features in feat_dir where the resulting-files parameters
        # are always concatenated in the following order:
        # (energy, fb, cep, bnf, vad_label).
        # SKIPPED: list to track faulty-files
        SKIPPED = []
        for show, channel in zip(show_list, channel_list):
            try:
                extractor.save(show, channel)
            except RuntimeError:
                print("SKIPPED")
                SKIPPED.append(show)
                continue
        print("Number of skipped:", len(SKIPPED))
        for show in SKIPPED:
            print(show)

        #BUG: The following lines do the exact same thing
        # as the few ones above, but with using multi-processing where
        # num_thread: is the number of parallel process to run
        # This method freezes after sometime, so you can try it
        # extractor.save_list(show_list=show_list,
        #                     channel_list=channel_list,
        #                     num_thread=self.NUM_THREADS)


    def __createFeatureServer(self, group=None):
        if group:
            feat_dir = os.path.join(self.base_dir, "feat", group)
        else:
            feat_dir = os.path.join(self.base_dir, "feat")
        # feature_filename_structure: structure of the filename to use to load HDF5 files
        # dataset_list: string of the form ["cep", "fb", vad", energy", "bnf"]
        # feat_norm: type of normalization to apply as post-processing
        # delta: if True, append the first order derivative
        # double_delta: if True, append the second order derivative
        # rasta: if True, perform RASTA filtering
        # keep_all_features: boolean, if True, keep all features, if False, keep frames according to the vad labels
        server = sidekit.FeaturesServer(feature_filename_structure=os.path.join(feat_dir, "{}.h5"),
                                        dataset_list=["vad", "energy", "cep", "fb"],
                                        feat_norm="cmvn",
                                        delta=True,
                                        double_delta=True,
                                        rasta=True,
                                        keep_all_features=True)
        print(server)
        return server


    def train(self, SAVE_FLAG=True):
        #Universal Background Model Training
        #SEE: https://projets-lium.univ-lemans.fr/sidekit/tutorial/ubmTraining.html
        train_list = os.listdir(os.path.join(self.base_dir, "audio", "enroll"))
        for i in range(len(train_list)):
            train_list[i] = train_list[i].split(".h5")[0]
        print("Creating Feature-Server:")
        server = self.__createFeatureServer("enroll")

        print("Training...")
        ubm = sidekit.Mixture()
        # Expectation-Maximization estimation of the Mixture parameters.
        ubm.EM_split(features_server=server, #sidekit.FeaturesServer used to load data
                     feature_list=train_list, # list of feature files to train the model
                     distrib_nb=self.NUM_GUASSIANS, # final number of Gaussian distributions
                     iterations=(1, 2, 2, 4, 4, 4, 4, 8, 8, 8, 8, 8, 8), # list of iteration number for each step of the learning process
                     num_thread=self.NUM_THREADS, # number of thread to launch for parallel computing
                     save_partial=True # if False, it only saves the last model
                     )
        # ->1 iteration of EM with 1 distribution
        # -> 2 iterations of EM with 2 distributions
        # -> 2 iterations of EM with 4 distributions
        # -> 4 iterations of EM with 8 distributions
        # -> 4 iterations of EM with 16 distributions
        # -> 4 iterations of EM with 32 distributions
        # -> 4 iterations of EM with 64 distributions
        # -> 8 iterations of EM with 128 distributions
        # -> 8 iterations of EM with 256 distributions
        # -> 8 iterations of EM with 512 distributions
        # -> 8 iterations of EM with 1024 distributions

        model_dir = os.path.join(self.base_dir, "ubm")
        if SAVE_FLAG:
            modelname = "ubm_{}.h5".format(self.NUM_GUASSIANS)
            print("Saving the model {} at {}".format(modelname, model_dir))
            ubm.write(os.path.join(model_dir, modelname))



    def evaluate(self):
        ##################################################################
        ############################# READING ############################
        ##################################################################
        # Create Feature server
        server = self.__createFeatureServer()
        # Read idmap for the enrolling data
        enroll_idmap = sidekit.IdMap.read(os.path.join(self.base_dir, "task", "idmap_enroll.h5"))
        # Reading the key
        key = sidekit.Key.read_txt(os.path.join(self.base_dir, "task", "test_trials.txt"))
        # return
        # Read the index for the test datas
        test_ndx = sidekit.Ndx.read(os.path.join(self.base_dir, "task", "test_ndx.h5"))
        # Read the UBM model
        ubm = sidekit.Mixture()
        model_name = "ubm_{}.h5".format(self.NUM_GUASSIANS)
        ubm.read(os.path.join(self.base_dir, "ubm", model_name))
        ##################################################################
        ############################ CREATING ############################
        ##################################################################
        # Create StatServer to load the enrollment data
        enroll_stat = sidekit.StatServer(statserver_file_name=enroll_idmap,
                                         distrib_nb=self.NUM_GUASSIANS,
                                         feature_size=100)
        # Compute the sufficient statistics
        enroll_stat.accumulate_stat(ubm=ubm,
                                    feature_server=server,
                                    seg_indices=range(enroll_stat.segset.shape[0]),
                                    num_thread=self.NUM_THREADS)
        # Save the status of the enroll data
        enroll_stat.write(os.path.join(self.base_dir, "task", "enroll_stat.h5"))
        # MAP adaptation of enrollment speaker models
        enroll_sv = enroll_stat.adapt_mean_map_multisession(ubm=ubm,
                                                            r=3 # MAP regulation factor
                                                            )
        # Compute scores
        scores_gmm_ubm = sidekit.gmm_scoring(ubm=ubm,
                                             enroll=enroll_sv,
                                             ndx=test_ndx,
                                             feature_server=server,
                                             num_thread=self.NUM_THREADS
                                            )
        # Save the model's Score object
        scores_gmm_ubm.write(os.path.join(self.base_dir, "ubm", "test_scores.h5"))
        ##################################################################
        ############################ CREATING ############################
        ##################################################################
        # Make DET plot
        prior = sidekit.logit_effective_prior(0.01, 10, 1)
        dp = sidekit.DetPlot(window_style='sre10', plot_title='Scores GMM-UBM')
        dp.create_figure()
        dp.set_system_from_scores(scores_gmm_ubm, key, sys_name='GMM-UBM')
        dp.plot_rocch_det()
        dp.plot_DR30_both(idx=0)
        dp.plot_mindcf_point(prior, idx=0)

        dp.__figure__.show() # Display figure
        dp.__figure__.savefig(os.path.join(self.base_dir, "DET_GMM_UBM.png"))





if __name__ == "__main__":
    ubm = SpeakerRecognizer()
    # ubm.extractFeatures("data")
    # ubm.extractFeatures("enroll")
    # ubm.extractFeatures("test")
    # ubm.train()
    ubm.evaluate()