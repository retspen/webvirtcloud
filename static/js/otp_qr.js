// The mailed OTP link carries its token after "#", which no request sends,
// so it is in no access log: the page posts it to get the QR code. A signed
// token has a ":"; another fragment (the "Skip to content" link's) is not one.
var otpQrForm = document.getElementById("otp-qr-form");
if (otpQrForm && location.hash.includes(":")) {
    otpQrForm.elements.token.value = location.hash.slice(1);
    history.replaceState(null, "", location.pathname);
    otpQrForm.submit();
}
