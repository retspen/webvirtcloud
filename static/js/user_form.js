// The user form (admin/user_form.html): a superuser needs no quota or
// permissions, so their sections hide while Superuser is chosen; a limit's
// No limit box disables its number, which the server then keeps as -1.
document.querySelectorAll('input[name=role]').forEach((radio) => radio.addEventListener('change', () => {
    const superuser = radio.value === 'superuser';
    document.querySelectorAll('[data-not-superuser]').forEach((section) => { section.hidden = superuser; });
    document.getElementById('superuser-note').hidden = !superuser;
}));
document.querySelectorAll('[data-no-limit]').forEach((box) => box.addEventListener('change', () => {
    document.getElementById(box.dataset.noLimit).disabled = box.checked;
}));
