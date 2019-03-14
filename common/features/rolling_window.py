#TODO: Moving features for retail benchmark

import pandas as pd
from functools import reduce
from sklearn.base import BaseEstimator
from .lag import SameWeekDayHourLagFeaturizer


class SameWeekDayHourRollingFeaturizer(BaseEstimator):
    def __init__(self, df_config, input_col_name,
                 window_size, start_week, training_df=None,
                 agg_count=1, agg_func='mean', q=None,
                 output_col_prefix='rolling_agg_lag_',
                 max_test_timestamp=None):
        self.time_col_name = df_config['time_col_name']
        self.value_col_name = df_config['value_col_name']
        self.grain_col_name = df_config['grain_col_name']
        self.frequency = df_config['frequency']
        self.time_format = df_config['time_format']

        self.input_col_name = input_col_name
        self.window_size = window_size
        self.start_week = start_week
        self.agg_count = agg_count
        self.agg_func = agg_func
        self.q = q
        self.output_col_prefix = output_col_prefix

        self._is_fit = False

        self.training_df = training_df
        self.max_test_timestamp = max_test_timestamp

    @property
    def training_df(self):
        return self._training_df

    @training_df.setter
    def training_df(self, val):
        self._training_df = val

    def same_weekday_hour_rolling_agg(self, input_df, forecast_creation_time):
        """
        Creates a series of aggregation features by calculating mean, quantiles,
        or std of values of the same day of week and same hour of day of previous weeks.
        Args:
            datetime_col: Datetime column
            value_col: Feature value column to create aggregation features from.
            window_size: Number of weeks used to compute the aggregation.
            start_week: First week of the first aggregation feature.
            count: Number of aggregation features to create.
            forecast_creation_time: The time point when the feature is created.
                This value is used to prevent using data that are not available
                at forecast creation time to compute features.
            agg_func: Aggregation function to apply on multiple previous values,
                accepted values are 'mean', 'quantile', 'std'.
            q: If agg_func is 'quantile', taking value between 0 and 1.
            output_col_prefix: Prefix of the output columns. The start week of each
                moving average feature is added at the end. Default value 'moving_agg_lag_'.
        Returns:
            pandas.DataFrame: data frame containing the newly created lag features as
                columns.
        For example, start_week = 9, window_size=4, and count = 3 will
        create three aggregation of features.
        1) moving_agg_lag_9: aggregate the same day and hour values of the 9th,
        10th, 11th, and 12th weeks before the current week.
        2) moving_agg_lag_10: aggregate the same day and hour values of the
        10th, 11th, 12th, and 13th weeks before the current week.
        3) moving_agg_lag_11: aggregate the same day and hour values of the
        11th, 12th, 13th, and 14th weeks before the current week.
        """
        datetime_col = input_df[self.time_col_name]
        input_col = input_df[self.input_col_name]

        df = pd.DataFrame({'Datetime': datetime_col, 'value': input_col})
        df.set_index('Datetime', inplace=True)

        df = df.asfreq('H')

        if not df.index.is_monotonic:
            df.sort_index(inplace=True)
        ## TODO: double check this
        df['fct_diff'] = df.index - forecast_creation_time
        df['fct_diff'] = df['fct_diff'].apply(
            lambda x: x.days * 24 + x.seconds / 3600)
        max_diff = max(df['fct_diff'])

        for i in range(self.agg_count):
            output_col = self.output_col_prefix + str(self.start_week + i)
            week_lag_start = self.start_week + i
            hour_lags = \
                [(week_lag_start + w) * 24 * 7 for w in range(self.window_size)]
            hour_lags = [h for h in hour_lags if h > max_diff]
            if len(hour_lags) > 0:
                tmp_df = df[['value']].copy()
                tmp_col_all = []
                for h in hour_lags:
                    tmp_col = 'tmp_lag_' + str(h)
                    tmp_col_all.append(tmp_col)
                    tmp_df[tmp_col] = tmp_df['value'].shift(h)

                if self.agg_func == 'mean' and self.q is None:
                    df[output_col] = round(tmp_df[tmp_col_all].mean(axis=1))
                elif self.agg_func == 'quantile' and self.q is not None:
                    df[output_col] = \
                        round(tmp_df[tmp_col_all].quantile(self.q, axis=1))
                elif self.agg_func == 'std' and self.q is None:
                    df[output_col] = round(tmp_df[tmp_col_all].std(axis=1))

        df.drop(['fct_diff', 'value'], inplace=True, axis=1)

        return df

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        if self.training_df is not None:
            forecast_creation_time = self.training_df[self.time_col_name].max()
            X = pd.concat([self.training_df, X], sort=True)
        else:
            max_train_timestamp = X[self.time_col_name].max()
            train_test_timestamp_diff = \
                self.max_test_timestamp - max_train_timestamp
            forecast_creation_time = max_train_timestamp - train_test_timestamp_diff
            X = X.copy()

        if self.grain_col_name is None:
            output_tmp = \
                self.same_weekday_hour_rolling_agg(X, forecast_creation_time)
            if self.training_df is not None:
                output_tmp = output_tmp.loc[X[self.time_col_name] >
                                            forecast_creation_time].copy()
            X = pd.merge(X, output_tmp, on=self.time_col_name)
        else:
            if isinstance(self.grain_col_name, list):
                col_names = [self.time_col_name, self.input_col_name] + \
                            self.grain_col_name
                merge_col_names = [self.time_col_name] + self.grain_col_name
            else:
                col_names = [self.time_col_name, self.input_col_name,
                             self.grain_col_name]
                merge_col_names = [self.time_col_name, self.grain_col_name]
            output_tmp = \
                X[col_names].groupby(self.grain_col_name).apply(
                    lambda g: self.same_weekday_hour_rolling_agg(
                        g, forecast_creation_time))
            output_tmp.reset_index(inplace=True)

            if self.training_df is not None:
                output_tmp = output_tmp.loc[output_tmp[self.time_col_name] >
                                            forecast_creation_time].copy()

            X = pd.merge(X, output_tmp, on=merge_col_names)
        if X.shape[0] == 0:
            raise Exception('The featurizer output is empty. Set the '
                            'training_df property of the featurizer to '
                            'None if transforming training data.')
        return X

