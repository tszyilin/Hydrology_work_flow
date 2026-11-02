function [a]=wjcmtrim(z)

% function trims leading and trailing blanks from string
%
a=fliplr(deblank(fliplr(deblank(z))));


