import React from 'react';
import PropTypes from 'prop-types';
import Avatar from '@material-ui/core/Avatar';
import Button from '@material-ui/core/Button';
import CssBaseline from '@material-ui/core/CssBaseline';
import FormControl from '@material-ui/core/FormControl';
import Input from '@material-ui/core/Input';
import InputLabel from '@material-ui/core/InputLabel';
import LockIcon from '@material-ui/icons/LockOutlined';
import Paper from '@material-ui/core/Paper';
import Typography from '@material-ui/core/Typography';
import withStyles from '@material-ui/core/styles/withStyles';
import {Link} from "react-router-dom";

const styles = theme => ({
  layout: {
    width: 'auto',
    display: 'block',
    marginLeft: theme.spacing.unit * 3,
    marginRight: theme.spacing.unit * 3,
    [theme.breakpoints.up(400 + theme.spacing.unit * 3 * 2)]: {
      width: 400,
      marginLeft: 'auto',
      marginRight: 'auto',
    },
  },
  paper: {
    marginTop: theme.spacing.unit * 8,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: `${theme.spacing.unit * 2}px ${theme.spacing.unit * 3}px ${theme.spacing.unit * 3}px`,
  },
  avatar: {
    margin: theme.spacing.unit,
    backgroundColor: theme.palette.secondary.main,
  },
  form: {
    width: '100%',
    marginTop: theme.spacing.unit,
  },
  submit: {
    marginTop: theme.spacing.unit * 3,
  },
  footer: {
    marginTop: theme.spacing.unit * 3,
    textAlign: 'center',
  },
});

class SignIn extends React.Component {
  constructor(props) {
    super(props);

    this.state = {
      user: {
        name: '',
        email: '',
        password: '',
      }
    };
  }
  /**
   * Change the user object.
   *
   * @param {object} event - the JavaScript event object
   */
  handleChange(event) {
    const field = event.target.name;
    const user = this.state.user;
    user[field] = event.target.value;

    this.setState({ user });
  }
  login() {
    return fetch('http://localhost:8000/api/v1/rest-auth/registration/', {
      method: 'POST',
      body: JSON.stringify({
        email: this.state.user.email,
        name: this.state.user.name,
        password: this.state.user.password,
      }),
    });
  }
  render() {
    const { classes } = this.props;
    return (
      <React.Fragment>
        <CssBaseline />
        <div className={classes.layout}>
          <Paper className={classes.paper}>
            <Avatar className={classes.avatar}>
              <LockIcon />
            </Avatar>
            <Typography variant="headline">Sign In</Typography>
            <form className={classes.form}>
              <FormControl margin="normal" required fullWidth>
                <InputLabel htmlFor="email">Email Address</InputLabel>
                <Input id="email" name="email" autoComplete="email" autoFocus />
              </FormControl>
              <FormControl margin="normal" required fullWidth>
                <InputLabel htmlFor="password">Password</InputLabel>
                <Input
                  name="password"
                  type="password"
                  id="password"
                  autoComplete="current-password"
                />
              </FormControl>
              <Button
                type="submit"
                fullWidth
                variant="raised"
                color="primary"
                className={classes.submit}
                onClick={this.login.bind(this)}
              >
                Sign In
              </Button>
            </form>
          </Paper>
          <footer className={classes.footer}>
            <Button size="small" component={Link} to="/auth/signup">Don't have an account? Sign Up</Button>
          </footer>
        </div>
      </React.Fragment>
    )
  }
}

SignIn.propTypes = {
  classes: PropTypes.object.isRequired,
};

export default withStyles(styles)(SignIn);
