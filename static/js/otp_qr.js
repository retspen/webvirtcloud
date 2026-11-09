// The mailed OTP link carries its token after "#", which no request sends,
// so it is in no access log: the page posts it to get the QR code.
var otpQrForm = document.getElementById("otp-qr-form");
if (otpQrForm && location.hash.length > 1) {
    otpQrForm.elements.token.value = location.hash.slice(1);
    history.replaceState(null, "", location.pathname);
    otpQrForm.submit();
}
